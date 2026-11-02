# SPDX-License-Identifier: BSD-3-Clause
"""Where every ``STOCK_V35`` field comes from, machine-readable.

``arrayprobe.profiles.STOCK_V35`` carries the values; this table carries the
``file:line`` in ``UIOPS-v3.5/joefinlon-UIOPS-039be82/`` that each value was read
from and the token the cited line must contain. ``tests/test_stock_v35_profile.py``
reads the cited lines back and compares the values to an Octave-parsed golden, so
the profile, this table and the vendored source can only agree by being right.

The v3.5 engine takes no ``FidelityProfile`` (``spec.py``, ``sizedist.py``,
``imgproc.py`` each say why: v3.5 has one source tree). Only ``reject_thresholds``
is consumed by it; the other fields describe the tree for ``.call`` sidecars and
readers.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Provenance", "STOCK_V35_PROVENANCE", "V35_TREE"]

V35_TREE = ("UIOPS-v3.5", "joefinlon-UIOPS-039be82")


@dataclass(frozen=True)
class Provenance:
    """One cited value of ``STOCK_V35``: the profile ``field``, the ``value`` it carries, and the
    ``file`` (relative to :data:`V35_TREE`, e.g. ``calculate_reject_unified.m`` or
    ``read_binary_SPEC.m``), ``lines`` and ``token`` it was read from."""
    field: str          #: FidelityProfile field, or "reject_thresholds.<name>"
    value: object       #: what STOCK_V35 carries
    file: str           #: relative to V35_TREE
    lines: tuple[int, ...]
    token: str          #: text every cited line must contain


_UNIFIED = "calculate_reject_unified.m"

STOCK_V35_PROVENANCE: tuple[Provenance, ...] = (
    Provenance("spec_buffer_guard", True, "read_binary_SPEC.m",
               (322, 326, 333, 356, 360, 367), "length(buf)"),
    # hvps_reader: read_binary_hvps.m is absent from the tree -- tested separately.
    Provenance("hvps_reader", "spec", "read_binary_SPEC.m", (1,),
               "function read_binary_SPEC("),
    Provenance("diode_stats_counts_shadowed", True, "imgProc_sm.m",
               (1208, 1210, 1211), "sum(c=='0',1)"),
    Provenance("zero_image_particle_recovery", True, "imgProc_sm.m",
               (773, 1311), "start = j + 2"),
    Provenance("time_in_seconds_from_tas", True, "imgProc_sm.m",
               (1133,), "tas2d = tas(tasTime==tempTime)"),
    Provenance("inter_arrival_in_seconds", True, "imgProc_sm.m", (1176,),
               "images.int_arrival(kk) = time_in_seconds(kk)-time_in_seconds(kk-1)"),
    # shadow_diode_reillumination: () means the token must occur NOWHERE in the file.
    Provenance("shadow_diode_reillumination", False, "imgProc_sm.m", (),
               "shadow_diode"),
    Provenance("imgproc_output_typing", "typed", "imgProc_sm.m",
               (1352,), "int16(images.auto_reject)"),
    Provenance("nan_tas_substitution", True, "sizeDist.m",
               (1962,), "if isnan(tas(i))"),
    Provenance("reject_thresholds.rej_zero_area", True, _UNIFIED,
               (60,), "handles.rej_zero_area = 1;"),
    Provenance("reject_thresholds.rej_split", True, _UNIFIED,
               (61,), "handles.rej_split = 1;"),
    Provenance("reject_thresholds.rej_hollow", True, _UNIFIED,
               (62,), "handles.rej_hollow = 1;"),
    Provenance("reject_thresholds.shadowed_area", 25, _UNIFIED,
               (64,), "handles.shadowed_area = 25;"),
    Provenance("reject_thresholds.max_edge_img_ar", 6, _UNIFIED,
               (65,), "handles.max_edge_img_ar = 6;"),
    Provenance("reject_thresholds.max_comp_img_ar", 5, _UNIFIED,
               (66,), "handles.max_comp_img_ar = 5;"),
)
