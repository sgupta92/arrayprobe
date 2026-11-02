# SPDX-License-Identifier: BSD-3-Clause
"""Plan row 11's "six-D_max switch + sensitivity table": how much the choice
of ``d_choice`` (``sizeDist.m:755-767``) actually matters on real particles.

The port's own six diameter definitions already exist and are faithfully
reproduced -- ``arrayprobe.sizedist._D_CHOICE_SPECS`` -- this module adds
nothing to the port itself (no fidelity question here) and never invents a
seventh. What did not exist: a way to see, on one set of real particles, how
far the six answers actually diverge for the same particle. That is a
capability question, not a correction, so it lives here rather than in the
port -- the same reasoning ``arco_export.py``/``particle_clustering.py`` use.

Reuses the port's own diameter functions directly rather than re-deriving
them, so a change to the port's own d_choice math is reflected here
automatically instead of silently going stale.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from arrayprobe_uiops.sizedist_core import _D_CHOICE_SPECS

__all__ = ["DChoiceSensitivity", "compute_sensitivity"]


@dataclass(frozen=True)
class DChoiceSensitivity:
    """Per-particle diameters under all six ``d_choice`` definitions, and the
    spread across them for each particle."""

    d_choice_labels: tuple[str, ...]
    diameters: np.ndarray
    """Shape ``(n_particles, 6)``, column order matching ``d_choice_labels``."""

    @property
    def spread_absolute(self) -> np.ndarray:
        """Per-particle ``max - min`` across the six choices, same units as
        ``diameters`` (mm, per the port's own convention). A particle with a
        NaN in any column (a zero-image artifact reading ``image_diam_minR``
        as unset, for example) gets a NaN spread rather than a silently
        wrong number from ignoring that column."""
        return self.diameters.max(axis=1) - self.diameters.min(axis=1)

    @property
    def spread_relative(self) -> np.ndarray:
        """Per-particle spread as a fraction of the mean of the six choices.
        Undefined (``nan``) where the mean is zero."""
        mean = self.diameters.mean(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(mean != 0, self.spread_absolute / mean, np.nan)

    def summary(self) -> dict[str, float]:
        """Pooled statistics across every particle -- the sensitivity table's
        headline numbers. Particles with a non-finite spread (e.g. an
        all-zero image) are excluded from the pooled statistics and counted
        separately, rather than silently propagating a NaN into every number
        or silently dropping them with no record."""
        rel = self.spread_relative
        abs_ = self.spread_absolute
        finite_rel = rel[np.isfinite(rel)]
        finite_abs = abs_[np.isfinite(abs_)]
        return {
            "n_particles": int(self.diameters.shape[0]),
            "n_excluded_non_finite": int(np.sum(~np.isfinite(abs_))),
            "mean_relative_spread_pct": (float(100.0 * finite_rel.mean())
                                        if finite_rel.size else float("nan")),
            "max_relative_spread_pct": (float(100.0 * finite_rel.max())
                                       if finite_rel.size else float("nan")),
            "mean_absolute_spread_mm": (float(finite_abs.mean())
                                       if finite_abs.size else float("nan")),
        }


def compute_sensitivity(image_length, image_width, diodesize: float,
                        image_diam_minR, *, engine: str = "3.1.4") -> DChoiceSensitivity:
    """The six ``d_choice`` diameters for every particle, side by side.

    ``image_length``/``image_width`` are the raw ``int16`` proc-file columns
    (the port's own A2 saturation behaviour is preserved automatically,
    since this calls the port's own functions rather than reimplementing
    them); ``image_diam_minR`` is the already-computed minimum-enclosing-
    circle diameter (``d_choice == 6`` reads it directly, per
    ``sizeDist.m:766``).

    ``engine`` (added 2026-09-14) selects which port's own d_choice
    computation is reused. ``"3.1.4"`` is the default and is byte-identical
    to this function's behaviour before ``engine`` existed: it calls
    ``arrayprobe.sizedist``'s six ``_D_CHOICE_SPECS`` functions directly, so
    A2's ``int16 x double`` saturation is preserved for ``d_choice`` 1, 2, 3
    and 5. ``"3.5"`` calls ``arrayprobe_uiops.sizedist.d_choice_diameter``
    instead, which casts ``image_length``/``image_width`` to ``float64``
    *before* the sizing multiply -- v3.5 ``sizeDist.m:941-942`` (verified by
    this stage; the module's own docstring cites ``:938-939``, three lines
    off) -- so A2 does not reproduce under this engine for any ``d_choice``.
    The six branches themselves are ``sizeDist.m:1054-1066`` (verified; the
    module docstring cites ``:1049-1063``). ``d_choice == 6`` reads
    ``image_diam_minR`` straight from the file on both engines and is
    therefore identical regardless of ``engine``.
    """
    image_length = np.asarray(image_length)
    image_width = np.asarray(image_width)
    image_diam_minR = np.asarray(image_diam_minR, dtype=float)

    if engine not in ("3.1.4", "3.5"):
        raise ValueError(f"dmax_sensitivity: engine must be '3.1.4' or '3.5', got {engine!r}")

    labels = []
    columns = []
    if engine == "3.1.4":
        for _n, _key, fn, label, _cite in _D_CHOICE_SPECS:
            labels.append(label)
            columns.append(np.asarray(
                fn(image_length, image_width, diodesize, image_diam_minR), dtype=float))
    else:
        from arrayprobe_uiops.sizedist import d_choice_diameter
        for _n, _key, _fn, label, _cite in _D_CHOICE_SPECS:
            labels.append(label)
            columns.append(np.asarray(
                d_choice_diameter(_n, image_length, image_width, diodesize, image_diam_minR),
                dtype=float))

    return DChoiceSensitivity(
        d_choice_labels=tuple(labels),
        diameters=np.column_stack(columns),
    )
