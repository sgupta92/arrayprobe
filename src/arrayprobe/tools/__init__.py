# SPDX-License-Identifier: BSD-3-Clause
"""Tooling that ships *inside* the installed package.

**Why this subpackage exists** (the ten-minute quickstart).
``scripts/`` holds the project's scripts, and
``[tool.setuptools.packages.find] where = ["src"]`` means none of them are
installed: ``pip install arrayprobe`` gives you the ``arrayprobe`` console
script and nothing else. So every command the documentation offers a stranger
-- including the quickstart's own first step -- worked only from a git clone,
which is the opposite of what a quickstart is for.

Modules land here when they are reachable from the installed package, i.e.
they import from ``arrayprobe`` and nothing outside it. ``make_demo_flight``
qualifies (``arrayprobe.readers.spec`` and numpy). Two scripts measurably do
not, and are named rather than silently left behind:

* ``scripts/run_flight.py`` -- 1,842 lines, referenced 435 times across 27 test
  modules, and its ``--jobs``/``--chunks`` workers re-exec
  ``sys.executable str(Path(__file__).resolve())``, so moving it changes the
  path two subprocess re-exec paths depend on. A real move, not a hard one to
  get wrong quietly; sized here so whoever takes it starts from the measurement.
* ``scripts/reprocess.py`` -- small and self-contained *except* that it loads
  ``run_flight`` (a private copy per call) for its stamp labels and the S3/S4
  stage functions. It follows ``run_flight``; it cannot lead. ``arrayprobe
  reprocess`` reaches it by path, the way ``arrayprobe run`` reaches
  ``run_flight``.
"""
