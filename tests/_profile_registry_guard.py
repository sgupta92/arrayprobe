# SPDX-License-Identifier: BSD-3-Clause
"""Snapshot and restore the live fidelity-profile registry around a test module or class.

``register_profile()`` mutates module-level state in :mod:`arrayprobe.profiles` that
outlives the test that caused it, and so does *importing* a registering module
(``arrayprobe_uiops.register_image_assisted``, ``arrayprobe_uiops.register_arm_stock``),
because the import runs the registration once and is then cached in ``sys.modules``.
A registration left behind leaks into every later test in the same process -- e.g. a
``read-binary --help`` rendering that lists ``PROFILES``.

Four pieces of state are restored, not one: ``_REGISTRY``, ``_V35_TREE_PROFILES`` (the
v3.5-gate declaration set), the two register-once caches (otherwise a later
``register_*()`` call returns its cached object without re-registering it), and
``sys.modules`` entries for the registering modules (otherwise a later ``import``
re-registers nothing). Restoring removes what was added; it never relies on re-import.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager

#: Modules whose import registers a profile as a side effect.
REGISTERING_MODULES = (
    "arrayprobe_uiops.register_image_assisted",
    "arrayprobe_uiops.register_arm_stock",
)

#: Register-once caches that register_profile() fills, as (module, attribute). The
#: image-assisted cache lives in arrayprobe_uiops.profiles (since split slice 10a(ii));
#: the two ARM ENA caches in arrayprobe_uiops.register_arm_stock, so they are read only
#: while that module is imported (a module popped by restore() starts its caches afresh).
_REGISTER_CACHES = (
    ("arrayprobe_uiops.profiles", "_image_assisted_v35_cache"),
    ("arrayprobe_uiops.register_arm_stock", "_arm_ena_stock_v35_cache"),
    ("arrayprobe_uiops.register_arm_stock", "_arm_ena_cold_v35_cache"),
)


def snapshot() -> dict:
    from arrayprobe import profiles
    from arrayprobe_uiops import profiles as _v35p  # noqa: F401 -- imported so its cache is read
    return {
        "registry": dict(profiles._REGISTRY),
        "v35": set(profiles._V35_TREE_PROFILES),
        "caches": {(m, c): getattr(sys.modules[m], c) for m, c in _REGISTER_CACHES
                   if m in sys.modules},
        "modules": {m for m in REGISTERING_MODULES if m in sys.modules},
    }


def restore(state: dict) -> None:
    from arrayprobe import profiles
    # Shipped lazily-built profiles (stock-v3.5, oracles-production-v3.5) are
    # kept if built since the snapshot: their caches are not reset, so their
    # _REGISTRY entries must stay consistent with them.
    keep = {n: p for n, p in profiles._REGISTRY.items() if n in profiles.SHIPPED}
    # ...and so must their v3.5-tree declarations: dropping one left a kept, cached
    # oracles-production-v3.5 in the registry but outside _V35_TREE_PROFILES, so a later
    # --engine 3.5 run refused it (found 2026-09-27, test_run_flight_profile_flag after
    # the CLI modules in one process).
    keep_v35 = {n for n in keep if n in profiles._V35_TREE_PROFILES}
    profiles._REGISTRY.clear()
    profiles._REGISTRY.update(state["registry"])
    for n, p in keep.items():
        profiles._REGISTRY.setdefault(n, p)
    profiles._V35_TREE_PROFILES.clear()
    profiles._V35_TREE_PROFILES.update(state["v35"])
    profiles._V35_TREE_PROFILES.update(keep_v35)
    for (m, c), v in state["caches"].items():
        if m in sys.modules:
            setattr(sys.modules[m], c, v)
    for m in REGISTERING_MODULES:
        if m not in state["modules"]:
            sys.modules.pop(m, None)
            pkg, _, attr = m.rpartition(".")
            if pkg in sys.modules and getattr(sys.modules[pkg], attr, None) is not None:
                delattr(sys.modules[pkg], attr)


@contextmanager
def preserved():
    state = snapshot()
    try:
        yield
    finally:
        restore(state)


def module_hooks():
    """Return ``(setUpModule, tearDownModule)`` that bracket a whole test module."""
    box: list = []

    def setUpModule():  # noqa: N802 -- unittest's name
        box.append(snapshot())

    def tearDownModule():  # noqa: N802 -- unittest's name
        if box:
            restore(box.pop())

    return setUpModule, tearDownModule
