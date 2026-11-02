# SPDX-License-Identifier: BSD-3-Clause
"""Tune loop: what a user can change, and whether a change reaches the output.

:mod:`arrayprobe.tune.settings` lists every setting a run on the v3.5 engine (the default engine)
can change, where each is set, and whether it has any effect on a given probe case.
:mod:`arrayprobe.tune.sample` draws review queues from a proc file (particles inside time windows,
per size bin) for the triage server.
:mod:`arrayprobe.tune.distributions` reports the per-particle distributions inside time
windows of a proc file, with each active threshold marked where it cuts.
:mod:`arrayprobe.tune.score` crosses a reviewer's triage labels with each queued particle's
reject code and size bin.  :mod:`arrayprobe.tune.diodes` reads a proc file's ``bin_stats`` as
lit counts and flags stuck diodes with the ORACLES fork's rule.  Nothing here runs the pipeline
or changes a computed number; ``sample`` writes only a queue file, and ``distributions``,
``score`` and ``diodes`` only a JSON report.
"""
