# SPDX-License-Identifier: BSD-3-Clause
"""``loadTASinfo_2DS.m`` -- read a flight's true-air-speed CSV sidecar.

``read_binary_SPEC.m``'s ``.tas.csv`` sidecar (written by
``read_binary_SPEC`` in the v3.1.4 validation engine (not included in this package) on this port's
side) has nine
columns; MATLAB's auto-generated importer keeps only the first two
(``timehhmmss``, ``tas``) via a ``'%f%f%*s%*s%*s%*s%*s%*s%*s'`` format string
-- there is no arithmetic anywhere in this function, only parsing.

**Octave cannot run the real source at all**, which is a real, worth-recording
limitation distinct from every other "runs fine under Octave" case this port
has found: ``textscan(fileID, formatSpec, endRow(1)-startRow(1)+1, ...)`` with
``endRow`` defaulting to ``Inf`` is accepted by MATLAB (documented behavior --
read to end of file) but Octave rejects the infinite repeat count outright
(``textscan: REPEAT = inf is too large``). ``octave_oracle/shims/loadTASinfo_2DS.m``
reproduces the same two-column parse by a different route and stands in as the
oracle -- "shim-derived" here means only "parsed by different code," a weaker
asterisk than ``CGAL_minR``'s, since no arithmetic differs at all.

That shim (and this port) both drop a trailing all-zero row when present: a
``dlmread`` artifact from a CSV that ends with a trailing newline, which the
real MATLAB ``textscan`` would not produce. A spurious ``(0, 0)`` sample would
put a zero TAS into the sample-volume calculation downstream, so dropping it
is required for fidelity to what ``textscan`` actually returns, not an
arbitrary cleanup.

Provenance: ``loadTASinfo_2DS.m`` (ORACLES-local code, not part of
distributed UIOOPS -- there is no upstream to report this to). Validated
against the Octave shim on a synthetic fixture:
``octave_oracle/run_s9_tasinfo_bank.py``, ``tests/test_readers_tasinfo.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

__all__ = ["load_tas_info"]


def load_tas_info(path) -> tuple[np.ndarray, np.ndarray]:
    """``[timehhmmss, tas] = loadTASinfo_2DS(filename)``.

    Returns ``(timehhmmss, tas)``, both 1-D ``float64`` arrays. Reads only
    the first two columns of the CSV; every other column (there are seven
    in a real ``.tas.csv``) is discarded, matching the source's own
    ``'%f%f%*s...'`` format string.
    """
    # usecols=(0, 1): the source's own '%f%f%*s...' skips every other column
    # unconditionally, whatever it holds -- reading only the first two here
    # means this doesn't choke on non-numeric content in the discarded ones.
    m = np.atleast_2d(np.loadtxt(Path(path), delimiter=",", usecols=(0, 1)))
    if m.size and np.all(m[-1] == 0):
        m = m[:-1]
    return m[:, 0], m[:, 1]
