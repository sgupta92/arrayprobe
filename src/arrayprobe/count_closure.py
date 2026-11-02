# SPDX-License-Identifier: BSD-3-Clause
"""Count closure: do a size-distribution product's binned counts sum to the particles S3 holds?

Read only.  Compares, for one size-distribution product (``sd`` netCDF) and its
per-particle proc file, **per second, the way sizeDist does**:

* ``binned``: the sum of ``count`` over bins (``sizedist.py:1408``,
  ``count = dist_minR * binwidth / 10``) per second;
* ``accepted``: the particles of the proc file that ``sizeDist`` puts in the
  accepted population of a second on the sd time axis.  Every particle that is
  not accepted is listed in ``excluded`` with a named cause and the port line
  that excludes it (``CAUSES``); the closure is exact or the residual is
  attributed particle by particle, never a tolerance.
* ``probe_reported``: the probe's own particle total.  Neither the SPEC reader's
  proc output nor the DMT proc output written by this package carries a
  per-second probe total that is read here, so it is ``None`` ("not available").

Causes, each measured on the tracked demo-flight fixtures:

``outside-tas-axis``
    The particle's second (probetype 2: ``Time`` in hhmmss, v3.5
    ``arrayprobe_uiops/sizedist.py:1562-1571``, v3.1.4: the v3.1.4 engine's sizedist
    module, lines 720-734)
    is not on the sd ``time`` axis, which is the TAS axis: sizeDist loops over
    ``n_sec = len(tas)`` seconds only (v3.5 ``:1510``/``:1608``, v3.1.4
    ``:691``/``:786``) and the last edge ``tas_time[-1] + 1`` is exclusive
    (v3.5 ``:1552``/``:1468``).  A block past the last TAS second is never read.
``shattered-interarrival``
    v3.1.4 with a shattering threshold (``iat_file`` -> ``'NONE'`` ->
    ``default_int_arr_thresh``, ``sizeDist.m:874``; the v3.1.4 engine's sizedist
    module, line 1217, whose line numbers the rest of this entry cites):
    the inter-arrival time, ``0`` for the file's first particle (``:906``) and
    ``diff(Time_in_seconds)`` to the previous particle in file order otherwise
    (``:909-911``), is ``<=`` the threshold, so ``auto_reject`` becomes ``'S'`` in
    memory (``:1221-1227``, ``sizeDist.m:876-888``, the hit and its predecessor).
    The proc file keeps its original code; the sd's ``Reject_ratio`` shows it.
``reject-code`` / ``center-out`` / ``diameter-out-of-bins``
    ``image_auto_reject`` not in ``GOOD_REJECT_CODES`` (``"0HhuR"``,
    ``sizedist_core.py:63``, ``sizeDist.m:1080``); ``image_center_in != 1`` under
    ``SAmethod == 0`` (``sizedist.py:1268-1270``); ``image_diam_minR`` outside
    ``[bin_min[0], bin_max[-1])`` (``bin_index``, ``sizedist_core.py:446-464``).

The shattering threshold is read from the sd ``.call`` sidecar
(``default_int_arr_thresh=<value>``) and applied only when the sd's
``Shattering Algorithm`` attribute says it was applied; a ``.call`` naming a real
threshold file is refused rather than guessed.  The v3.5 corrupt-time pass
(``while k < n - 1``) is not re-derived: it runs only on a
non-monotonic particle-time series (``arrayprobe_uiops/sizedist.py:498``), and
this module raises ``NotImplementedError`` on one instead of attributing silently.
"""
from __future__ import annotations

import os
import re

import numpy as np

from arrayprobe import provenance

GOOD_REJECT_CODES = "0HhuR"
NOT_AVAILABLE = "not available"
CAUSES = (
    "outside-tas-axis",
    "shattered-interarrival",
    "reject-code",
    "center-out",
    "diameter-out-of-bins",
)


def _var(ds, name):
    x = ds.variables[name][:]
    if np.ma.isMaskedArray(x) and not np.issubdtype(x.dtype, np.floating):
        # NaN is not a value of an integer dtype; a masked int (a netCDF fill value in an
        # int16/int32 particle variable) is widened to float64 so the fill can be NaN.
        x = x.astype(np.float64)
    return np.ma.filled(x, np.nan)


def _hhmmss_to_insec(t):
    t = np.asarray(t, dtype=np.float64)
    return (np.floor(t / 10000) * 3600 + np.floor((t % 10000) / 100) * 60
            + np.floor(t % 100))


def _shattering_threshold(sd_path, sd_attrs):
    """The per-particle threshold sizeDist applied, or ``None`` when it skipped the block."""
    alg = str(sd_attrs.get("Shattering Algorithm", "Not applied"))
    if alg.startswith("Not applied"):
        return None
    # The driver writes ``<file>.nc.call`` (``run_flight.call_path``); a hand-named
    # ``<stem>.call`` is the fallback, as in ``reproduce_report._call_stamp``.
    call = str(sd_path) + ".call"
    if not os.path.isfile(call):
        call = os.path.splitext(str(sd_path))[0] + ".call"
    if not os.path.isfile(call):
        raise FileNotFoundError(f"{call}: the sd stamp names the shattering threshold")
    with open(call, encoding="utf-8") as fh:
        fields = provenance.parse(fh.read()).fields
    # A field's value runs to the next key ("6e-06 (default)"); its first token is the value.
    iat_file = (fields.get("iat_file") or "").split()
    if iat_file and iat_file[0] not in ("<none>", "NONE") \
            and not iat_file[0].endswith("MISSING.cdf"):
        raise NotImplementedError(
            f"{call} names a real threshold file {iat_file[0]}; "
            "per-particle thresholds from a file are not re-derived here")
    m = re.match(r"[0-9.eE+-]+", fields.get("default_int_arr_thresh") or "")
    if m is None:
        raise ValueError(f"{call}: shattering was applied but no default_int_arr_thresh= stamp")
    return float(m.group(0))


def count_closure(sd_path, proc_path):
    """Return per-second ``binned``/``accepted``, the residual and every excluded particle."""
    import netCDF4

    with netCDF4.Dataset(str(sd_path)) as sd:
        counts = _var(sd, "count")                      # (Time, bins)
        bin_min = _var(sd, "bin_min")
        bin_max = _var(sd, "bin_max")
        times = _var(sd, "time")
        attrs = {k: sd.getncattr(k) for k in sd.ncattrs()}
    with netCDF4.Dataset(str(proc_path)) as pr:
        code = _var(pr, "image_auto_reject")
        center = _var(pr, "image_center_in")
        diam = _var(pr, "image_diam_minR")
        ptime = _var(pr, "Time")                        # hhmmss, probetype 2
        tsec = _var(pr, "Time_in_seconds")
        rec = _var(pr, "parent_rec_num")
    n = int(code.size)
    sa_method = attrs.get("SA Method")
    if sa_method is not None and str(sa_method) != "Center-in":
        # The center-out cause below is sizeDist's SAmethod == 0 rule only.
        raise NotImplementedError(
            f"SA Method {sa_method!r}: only the Center-in acceptance is re-derived")

    # -- the second each particle belongs to (sizeDist's TAS-axis loop) --------
    tas_time = _hhmmss_to_insec(times)
    if np.any(np.diff(tas_time) <= 0):
        raise NotImplementedError("non-monotonic sd time axis: fix_time_grid path not re-derived")
    image_time = _hhmmss_to_insec(ptime)
    if np.any(np.diff(image_time) < 0):
        raise NotImplementedError(
            "non-monotonic particle times: v3.5's corrupt-time pass is not re-derived")
    if tas_time.size:
        edges = np.concatenate([tas_time, [tas_time[-1] + 1]])
        sec_index = np.searchsorted(edges, image_time, side="right") - 1
    else:  # a zero-second sd: no particle lies on its axis
        sec_index = np.full(n, -1)
    on_axis = (sec_index >= 0) & (sec_index < len(tas_time))

    # -- shattering, v3.1.4 production gate (:866-888) --------------------------
    thresh = _shattering_threshold(sd_path, attrs)
    shattered = np.zeros(n, dtype=bool)
    if thresh is not None and n:
        int_arr = np.concatenate([[0.0], np.diff(tsec)])
        hit = int_arr <= thresh
        shattered = hit.copy()
        shattered[:-1] |= hit[1:]                      # :884-888 flags ix-1 and ix

    good_code = np.isin(code, [ord(c) for c in GOOD_REJECT_CODES])
    center_ok = center == 1
    in_range = (diam >= bin_min[0]) & (diam < bin_max[-1])

    excluded = []
    accepted = np.ones(n, dtype=bool)
    for k in range(n):
        cause = None
        if not on_axis[k]:
            cause = "outside-tas-axis"
        elif shattered[k]:
            cause = "shattered-interarrival"
        elif not good_code[k]:
            cause = "reject-code"
        elif not center_ok[k]:
            cause = "center-out"
        elif not in_range[k]:
            cause = "diameter-out-of-bins"
        if cause is not None:
            accepted[k] = False
            excluded.append({"index": k,
                             "parent_rec_num": None if np.isnan(rec[k]) else int(rec[k]),
                             "time": float(ptime[k]), "cause": cause})

    accepted_per_second = np.zeros(len(tas_time))
    for k in np.flatnonzero(accepted):
        accepted_per_second[sec_index[k]] += 1
    binned_per_second = np.nansum(counts, axis=1)
    total_binned = float(np.sum(binned_per_second))
    total_accepted = int(np.count_nonzero(accepted))
    return {
        "time": times,
        "binned_per_second": binned_per_second,
        "accepted_per_second": accepted_per_second,
        "total_binned": total_binned,
        "total_accepted": total_accepted,
        "total_in_proc": n,
        "residual": total_binned - total_accepted,
        "residual_per_second": binned_per_second - accepted_per_second,
        "excluded": excluded,
        "shattering_threshold": thresh,
        "probe_reported": None,
        "probe_reported_note": NOT_AVAILABLE,
    }
