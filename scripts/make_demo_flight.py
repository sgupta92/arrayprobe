# SPDX-License-Identifier: BSD-3-Clause
"""Re-export shim: the builder moved into the installed package.

The code now lives at :mod:`arrayprobe.tools.make_demo_flight` so that
``pip install arrayprobe`` actually ships it -- ``scripts/`` is not installed
(``packages.find where = ["src"]``), which meant the quickstart's own first
step worked only from a git clone. See that subpackage's ``__init__`` for why
this one moved and which two scripts measurably cannot follow it yet.

This file stays because the path is published: ``docs/_build/pages``'
user-guide quickstart (executed verbatim by ``tests/test_quickstart_runs.py``),
``12-orientation.md`` and ``README.md`` all name ``scripts/make_demo_flight.py``.
A shim keeps those true at no cost rather than churning five documents and a
test that deliberately reads what a stranger would type.

The preferred form for anyone installing the package is the subcommand::

    arrayprobe make-demo-flight base160101000000.2DS --seconds 5
"""

from __future__ import annotations

from arrayprobe.tools.make_demo_flight import (  # noqa: F401
    DEMO_AIRCRAFT_TAS_MPS,
    DENSE_BAR_LENGTH_SLICES,
    DENSE_BAR_WIDTH_DIODES,
    DENSE_DISK_DIAMETERS,
    DENSE_GAP_LONG,
    DENSE_GAP_SHORT,
    DENSE_RING_DIAMETER,
    bar_runs,
    build_demo_flight,
    build_dense_demo_flight,
    demo_aircraft_path,
    disk_runs,
    image_packet,
    main,
    raw_file,
    ring_runs,
    run_word,
    write_demo_aircraft,
)

if __name__ == "__main__":
    import sys

    # --help prints the docstring and does nothing else (tests/test_tools_help.py).
    if sys.argv[1:] in (["-h"], ["--help"]):
        print("usage: python scripts/make_demo_flight.py\n")
        print(__doc__)
        raise SystemExit(0)
    raise SystemExit(main())
