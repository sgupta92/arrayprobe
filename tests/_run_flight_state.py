# SPDX-License-Identifier: BSD-3-Clause
"""Snapshot and restore ``scripts/run_flight.py``'s UPPER_CASE module globals.

Every test module shares one ``sys.modules["run_flight"]`` object, and
``main()``, ``_apply_config`` and ``use_preset`` rebind its UPPER_CASE globals
(``ENGINE``, ``PROFILE``, ``PROBE_CASE``, ``CONFIG_PATH``, ``V35_CALL`` ...).
A test that calls them without restoring every one leaks run state into
whichever module runs next.
The snapshot is shallow: it restores each name's
binding, which is what those functions change.
The one exception is ``INVENTORY_ROWS``, a dict that ``inventory_preflight`` fills in
place and never rebinds, so a rebind-only restore would leave one test's rows for the next
decode of the same raw path to stamp: its contents are copied and put back too.
"""

from __future__ import annotations

_MISSING = object()

#: UPPER_CASE globals that are mutated in place, so their contents are snapshotted.
_MUTABLE_DICTS = ("INVENTORY_ROWS",)


class _Snapshot(dict):
    """name -> bound object, plus ``contents``: name -> a copy of each in-place dict."""

    contents: dict


def snapshot(module) -> dict:
    """The module's UPPER_CASE globals, name -> bound object."""
    saved = _Snapshot({k: v for k, v in vars(module).items() if k.isupper()})
    saved.contents = {k: dict(saved[k]) for k in _MUTABLE_DICTS if isinstance(saved.get(k), dict)}
    return saved


def restore(module, saved: dict) -> None:
    """Rebind every saved name, and delete UPPER_CASE names added since."""
    for name in [k for k in vars(module) if k.isupper() and k not in saved]:
        delattr(module, name)
    for name, value in saved.items():
        setattr(module, name, value)
    for name, rows in getattr(saved, "contents", {}).items():
        getattr(module, name).clear()
        getattr(module, name).update(rows)


def diff(module, saved: dict) -> list[str]:
    """Names whose binding differs from ``saved`` (added, removed or rebound)."""
    now = snapshot(module)
    rows = getattr(saved, "contents", {})
    return sorted(k for k in set(now) | set(saved)
                  if now.get(k, _MISSING) is not saved.get(k, _MISSING)
                  or now.contents.get(k, _MISSING) != rows.get(k, _MISSING))


def preserve(testcase, module) -> None:
    """Snapshot now and register the restore as a cleanup on ``testcase``
    (an instance, or a class inside ``setUpClass``)."""
    saved = snapshot(module)
    if isinstance(testcase, type):
        testcase.addClassCleanup(restore, module, saved)
    else:
        testcase.addCleanup(restore, module, saved)


def preserve_module(module) -> None:
    """Snapshot now and restore when the calling test module finishes: call it
    from ``setUpModule``, for a module that reaches the driver from many tests."""
    import unittest

    unittest.addModuleCleanup(restore, module, snapshot(module))
