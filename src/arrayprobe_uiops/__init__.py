# SPDX-License-Identifier: BSD-3-Clause
"""arrayprobe_uiops -- a Python port of UIOOPS carrying the developers' own fixes
for the findings the v3.1.4 port (``arrayprobe``) surfaced. Where a finding
was fixed upstream in v3.5, this package reproduces that fix; where v3.1.4's
behaviour was never touched by any later release, this package reproduces it
bug-for-bug the same way ``arrayprobe`` does.

Started 2026-09-10 (author-directed) as new, additional work alongside
the v3.1.4 port, not a replacement for it. Complete through all ten port stages as
of 2026-09-12, and the default for new work from that date by the author's
decision -- but ``arrayprobe`` is **not** deprecated and is not moving: it
stays live, importable and tested, and it remains what the paper, CI and the
archived-product validation cite, because no archived campaign product was
ever produced by v3.5. That v3.5 exists does not weaken the v3.1.4 fidelity claim
(two independent drifts
from a shared v3.1.4 base).

Zenodo DOI for the v3.5 release: 10.5281/zenodo.18945998.




**Reuse of the v3.1.4 port.** 18 of the 25 shared MATLAB/C++ files between
v3.1.4 and v3.5 are byte-identical (measured directly, not assumed -- see the
design doc's table). Where a whole module's source MATLAB file is
byte-identical, this package imports the v3.1.4 port's Python translation of
it directly rather than duplicating it -- the translation is provably still
correct, since nothing changed to translate. That reuse is guarded
mechanically, not merely documented:
``tests/test_v35_reuse_byte_identity.py`` hashes each reused
file's v3.1.4 and v3.5 source against each other and fails the moment they
diverge, so a future upstream point-release cannot silently invalidate a
reuse decision made here.
"""

import logging

__all__: list[str] = []

__version__ = "0.1.0"  # the distribution's version; tests/test_version.py

# Since 2026-09-15: NullHandler by default, matching ``arrayprobe``'s
# own package logger -- importing this package must never print anything;
# ``arrayprobe.cli`` attaches the real handler for the console script.
logging.getLogger(__name__).addHandler(logging.NullHandler())
