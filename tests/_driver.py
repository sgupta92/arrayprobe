# SPDX-License-Identifier: BSD-3-Clause
"""Where the flight driver's source text lives, defined once for the tests that read it.

The driver is five files (``DRIVER_FILES``). A test that *loads* the driver as a module
goes through ``scripts/<name>.py``, the entry point scripts, hooks and launch logs name.
A test that *reads, parses or sweeps* the driver's text goes through
``driver_source(name)``, so the text it checks is the driver's own wherever the driver
lives, and moving the driver changes ``DRIVER`` here and nowhere else.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

#: The directory holding the driver's source files: the installed package's own, so a
#: suite run from an unpacked sdist with ``src/`` moved away reads the wheel it installed.
DRIVER = Path(importlib.util.find_spec("arrayprobe.driver").submodule_search_locations[0])

#: The five files that make up the flight driver.
DRIVER_FILES = (
    "run_flight.py",
    "reprocess.py",
    "_load_record.py",
    "preflight_inputs.py",
    "tas_from_probe_housekeeping.py",
)


def driver_source(name: str) -> Path:
    """Return the path of the driver source file ``name`` (one of ``DRIVER_FILES``)."""
    if name not in DRIVER_FILES:
        raise ValueError(f"{name!r} is not a driver file; the driver is {DRIVER_FILES}")
    return DRIVER / name
