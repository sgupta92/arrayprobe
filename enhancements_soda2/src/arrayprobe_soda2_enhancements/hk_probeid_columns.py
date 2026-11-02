# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S5-k: ``spec_process_hk``'s voltage/count columns default to the
horizontal-channel set for every ``probeid`` but the literal string
``'V'``.

``spec_process_hk.pro:84-94`` tests ``op.probeid`` against the literal
``'V'``: when it matches, ``:85`` takes the voltages from the
vertical-channel housekeeping columns (4, 29, 30, 5, 31, 32, 6);
otherwise ``:90`` takes the horizontal-channel set (1, 25, 26, 2, 27,
28, 3), and the count columns follow the same split.

Every ``probeid`` other than the literal string ``'V'`` -- including
``soda2_update_op.pro:11``'s own default, ``'A0'``, and any misspelling
of ``'V'`` (e.g. lowercase ``'v'``) -- silently takes the horizontal
channel's columns, with no error or warning.

**Correction**: the register's own suggested edit -- a ``CASE`` that
refuses an unrecognised ``probeid`` rather than silently routing it to
the horizontal branch. The set of *recognised* horizontal ids is not
invented: it is exactly what this project's own test bank measured as
equivalent to the horizontal branch (``test_soda2_preloop.py::
test_line_84_probeid_A0_and_H_agree``, S5-k's own established note) --
``'H'`` and ``soda2_update_op.pro:11``'s default ``'A0'`` -- plus
``'V'`` for the vertical branch. Anything else (a misspelling such as
``'v'``, or any other string) raises rather than silently choosing a
channel.

``src/arrayprobe_soda2/process_hk.py`` is never imported
for writing and never modified. This module calls the real,
unmodified ``process_hk`` only after validating ``probeid``. Tests:
``tests/test_hk_probeid_columns.py``.
"""
from __future__ import annotations

from typing import Any

from arrayprobe_soda2.process_hk import HouseData, process_hk
from arrayprobe_soda2.spec_index import SpecIndex

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

__all__ = ["UnrecognizedProbeid", "corrected_process_hk"]

#: 'H' and the default 'A0' are measured equivalent to the horizontal
#: branch (test_soda2_preloop.py); 'V' selects the vertical branch.
#: Nothing beyond what this project's own bank has exercised.
_RECOGNIZED = frozenset({"V", "H", "A0"})


class UnrecognizedProbeid(ValueError):
    """``spec_process_hk.pro:84``: ``probeid`` is neither ``'V'`` nor a
    horizontal id this project's own test bank has confirmed equivalent
    to the horizontal branch (``'H'``, the default ``'A0'``) -- the
    port would otherwise silently route it to the horizontal channel's
    columns."""


def corrected_process_hk(op: dict[str, Any], y: SpecIndex | None = None) -> HouseData:
    """``spec_process_hk`` with S5-k corrected: raises
    :class:`UnrecognizedProbeid` before calling the port at all when
    ``op['probeid']`` (default ``'A0'``) is not one of ``_RECOGNIZED``."""
    probeid = str((op or {}).get("probeid", "A0"))
    if probeid not in _RECOGNIZED:
        raise UnrecognizedProbeid(
            f"spec_process_hk.pro:84: probeid={probeid!r} is not "
            f"recognized ({sorted(_RECOGNIZED)}) -- the port would "
            "otherwise silently take the horizontal channel's columns")
    return process_hk(op, y=y)


register(EnhancementSpec(
    name="hk_probeid_columns",
    summary="process_hk refuses an unrecognized probeid instead of "
            "silently taking the horizontal channel's volts/counts/"
            "overloads/laservolts columns for it.",
    finding="S5-k",
    reachability="flagged",
    entry_point="corrected_process_hk",
))
