# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""``arrayprobe-soda2-enhancements`` -- opt-in corrections for findings against
``arrayprobe_soda2``, NCAR SODA-2's Python port.

Requested 2026-09-14: *"same for soda - address any findings and start to create
its own enhancements 'version' that users could use. so we essentially create two packages -
v3.5 and soda with opt in enhancements."* This is the "soda" package that quote asks for,
built the same way ``arrayprobe_enhancements`` was built for UIOOPS: a separate distribution
that imports ``arrayprobe_soda2`` and never the reverse, so installing it is the opt-in and
the port stays importable, tested and byte-faithful with this package deleted.

Which findings are correctable here (Tier A)
and which are deferred is ``enhancements_soda2/BACKLOG_STATUS.md``.

**Dependency direction.** This package imports ``arrayprobe_soda2`` (packaged inside the
``arrayprobe`` distribution) and nothing else from this repository -- never ``arrayprobe``
(the UIOOPS v3.1.4 port), ``arrayprobe_uiops``, or ``arrayprobe_enhancements``. Two lineages,
never sharing a correction: ``arrayprobe_enhancements.applicability``'s ``ENGINES`` excludes
SODA-2 on the same grounds. Enforced by
``enhancements_soda2/tests/test_lineage_isolation.py`` (this package, an AST sweep for those
imports) and ``tests/test_no_enhancement_coupling.py`` (the port, an AST
sweep for any unconditional reference to this package).

**Opt-in, default OFF, same as ``arrayprobe_enhancements``** --
the port (``arrayprobe_soda2``) never applies a correction by itself, and every registered
module here is opt-in by name through :mod:`arrayprobe_soda2_enhancements.registry`, **except**
the five in ``registry.PROTECTIVE`` (corrections for data-destroying upstream defects), which
run by default on every SODA-2 probe -- SODA-2 has never written an archived product
for any probe, so the protective-corrections rule's "default-off on the lineage with an archived product" carve-out
excludes nothing here. See ``registry``'s own docstring.
"""

from __future__ import annotations

__all__: list[str] = []
