# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""The driver adapter: resolved corrections -> ``arrayprobe_soda2.enhancement_hooks`` substitutions.

Before this, ``arrayprobe soda2 run`` recorded the resolved ``[enhancements]``
table and applied nothing (``"skipped": {name: "no driver adapter"}``). This module turns a
resolved table into one replacement per hook point and installs them for the duration of a
``with`` block around ``soda2_process_2d``; the public entry is
:func:`arrayprobe_soda2_enhancements.registry.apply`.

Every registered correction is classified here as exactly one of:

* **routed** -- its entry point is a drop-in for one port binding (same call signature, same
  return type), listed in :data:`ROUTES`;
* **not driver-applicable**, with the reason, in :data:`NOT_ROUTED` -- a diagnostic that
  reports rather than corrects, a correction whose defect is inline arithmetic with no function
  boundary to substitute, or one whose signature needs a value the driver's call does not pass.

``test_adapter.py`` checks the two tables partition the registry, so a new correction cannot be
registered without a decision here.

**Composition.** Two corrections that act on one binding are composed into one callable rather
than stacked (the hooks module refuses stacking): ``aspr_nan_fix`` + ``den_clamp_fix`` share
``axis_and_ratio`` and compose through ``_aspect_ratio_recompute.recompute``'s two flags;
``label_blobs_int_count`` + ``dilation_clamp_fix`` share ``label_blobs`` and compose as "the
dilation branch with the clamp corrected, returning ``uint32`` labels when S4-y is also on".
``double_pi_fix`` replaces ``aspect_ratio`` and reads ``axis_and_ratio`` through the port module
at call time, so it composes with the first pair.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from arrayprobe_soda2 import enhancement_hooks

#: correction name -> hook point it is routed through.
ROUTES: dict[str, str] = {
    "last_buffer_index_fix": "spec_index",
    "pbp_rejectionflag_ubyte": "open_pbp_ncdf",
    "hk_probeid_columns": "process_hk",
    "same_time_buffer_fix": "process_spec_buffer",
    "blank_roi_dof_fix": "binary_dof",
    "no_stuck_diode_fix": "fixstuckbits",
    "label_blobs_int_count": "label_blobs",
    "dilation_clamp_fix": "label_blobs",
    "fillholes_int_labels": "fillholes",
    "poisson_fill_guard": "poisson_spot_correct",
    "zero_area_return_fix": "soda2_findsize",
    "double_pi_fix": "aspect_ratio",
    "aspr_nan_fix": "axis_and_ratio",
    "den_clamp_fix": "axis_and_ratio",
}

#: correction name -> why the driver adapter does not apply it.
NOT_ROUTED: dict[str, str] = {
    "rollover_modulus_fix": "inline arithmetic inside process_spec_buffer "
                            "(processbuffer_spec.py:305); no function boundary to substitute",
    "empty_roi_diodegaps_fix": "inline arithmetic inside process_buffer_tail "
                               "(processbuffer_tail.py:283); no function boundary to substitute",
    "pbp_inttime_consistent": "its writer needs `interarrival`, which the driver's "
                              "write_pbp_csv_buffer call (process_2d.py:389) does not pass",
    "rejection_tally_fix": "returns a separate corrected tally beside the port's own; "
                           "call it on the run's arrays, it substitutes no driver call",
    "run_diagnostics": "a diagnostic: reports on a run and changes no output",
}


def _entry(name: str) -> Callable[..., Any]:
    from arrayprobe_soda2_enhancements.registry import entry_point
    return entry_point(name)


def _axis_and_ratio(nan_fix: bool, den_fix: bool) -> Callable[..., Any]:
    from arrayprobe_soda2_enhancements._aspect_ratio_recompute import recompute

    def axis_and_ratio(x_ind, y_ind_adjusted, circle):
        r = recompute(x_ind, y_ind_adjusted, circle,
                      den_zero_guard=den_fix, aspr_nan_passthrough=nan_fix)
        return r.aspr, r.orientation
    return axis_and_ratio


def _label_blobs(int_fix: bool, dilation_fix: bool) -> Callable[..., Any]:
    from arrayprobe_soda2.label_blobs import label_blobs as port_label_blobs

    from arrayprobe_soda2_enhancements.dilation_clamp_fix import corrected_label_blobs_dilation

    def label_blobs(img, dilatelength: int = 0, all_neighbors: bool = False,
                    integer: bool = False, jit: bool = False):
        # `jit` is accepted here because this substitution stands in for the port's
        # own label_blobs, which gained the keyword on 2026-09-18 (the SODA-2
        # flood-fill kernel, 36.2x, byte-identical). A substitution that does not
        # track its target's signature raises TypeError at the first particle --
        # which is exactly what `corrected_fillholes` did the same day, and what
        # this call site was one `keeplargest != 0` away from doing.
        integer = integer or int_fix
        if dilation_fix and dilatelength != 0:
            # The dilation correction has no compiled path, so it takes the
            # reference route and `jit` is deliberately dropped: speed only, no
            # written byte moves either way.
            return corrected_label_blobs_dilation(img, dilatelength,
                                                  all_neighbors=all_neighbors, integer=integer)
        return port_label_blobs(img, dilatelength=dilatelength, all_neighbors=all_neighbors,
                                integer=integer, jit=jit)
    return label_blobs


def replacements(resolved: Mapping[str, bool]) -> tuple[dict[str, Callable[..., Any]],
                                                           dict[str, str]]:
    """``(hook point -> replacement, point -> the corrections composed into it)`` for every
    resolved-ON correction that is routed."""
    on = {n for n, v in resolved.items() if v and n in ROUTES}
    by_point: dict[str, list[str]] = {}
    for n in sorted(on):
        by_point.setdefault(ROUTES[n], []).append(n)
    repl: dict[str, Callable[..., Any]] = {}
    for point, names in by_point.items():
        if point == "axis_and_ratio":
            repl[point] = _axis_and_ratio("aspr_nan_fix" in names, "den_clamp_fix" in names)
        elif point == "label_blobs":
            repl[point] = _label_blobs("label_blobs_int_count" in names,
                                       "dilation_clamp_fix" in names)
        else:
            (only,) = names  # every other point has exactly one correction routed to it
            repl[point] = _entry(only)
    return repl, {p: ", ".join(ns) for p, ns in by_point.items()}


#: Where :func:`worker_replacements` is found from a fresh interpreter. A string rather than a
#: reference, because that is the whole point: a ``spawn``-started worker imports it by name.
WORKER_FACTORY = "arrayprobe_soda2_enhancements._adapter:worker_replacements"


def worker_replacements(resolved: Mapping[str, bool]) -> dict[str, Callable[..., Any]]:
    """:func:`replacements`' mapping, rebuilt in a process that has only ``resolved``.

    The entire route from a resolved table to a set of substitutions is a pure function of
    that table -- :func:`replacements` reads nothing else, and its two composed callables
    (:func:`_axis_and_ratio`, :func:`_label_blobs`) close over booleans drawn from it and
    over nothing from the caller. So the parent can ship the table, which is plain data and
    pickles, and a worker rebuilds the same callables here.

    ``load_all()`` first, and that is not a formality: registration is an import side effect,
    so in a fresh interpreter :data:`registry.REGISTRY` is empty and every ``entry_point``
    lookup below would raise ``UnknownEnhancement`` (stage 8 saw exactly this).
    """
    from arrayprobe_soda2_enhancements.registry import load_all
    load_all()
    return replacements(resolved)[0]


@contextmanager
def applied(resolved: Mapping[str, bool]) -> Iterator[dict[str, Any]]:
    """Install the routed corrections for the ``with`` block; yield the sidecar record
    ``{"applied": [...], "skipped": {name: reason}, "hook_points": {point: names}}``.
    ``skipped`` lists only resolved-ON corrections that were not applied.

    The substitution is installed **with a reconstruction plan**, so a split run
    (``soda2_process_2d(..., jobs=N)``) can rebuild these same corrections inside each worker
    instead of being refused. ``overridden`` calls the factory itself and checks it produces
    the same hook points, so the plan cannot drift away from what is installed here.
    """
    repl, composed = replacements(resolved)
    applied_names = sorted(n for n, v in resolved.items() if v and n in ROUTES)
    skipped = {n: NOT_ROUTED.get(n, "no route recorded in arrayprobe_soda2_enhancements._adapter")
               for n, v in sorted(resolved.items()) if v and n not in ROUTES}
    plan = enhancement_hooks.Reconstruction(factory=WORKER_FACTORY,
                                            payload={str(n): bool(v)
                                                     for n, v in sorted(resolved.items())})
    with enhancement_hooks.overridden(repl, reconstruction=plan):
        yield {"applied": applied_names, "skipped": skipped,
               "hook_points": dict(sorted(composed.items()))}
