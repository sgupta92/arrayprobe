# SPDX-License-Identifier: BSD-3-Clause
"""HHMMSS <-> seconds-since-midnight time conversions.

Ported from: hhmmss2insec.m, insec2hhmmss.m (UIOOPS v3.1.4)
"""

#: Declared so the public surface is explicit rather than whatever happens not to
#: start with an underscore. The Phase-1 shims at ``<name>.py`` in the original flat layout import
#: these names directly, CONSTANTS INCLUDED -- omitting a constant here would not
#: break them, but omitting one from a shim does, which is why they are listed.
__all__ = [
    "hhmmss_to_insec",
    "insec_to_hhmmss",
]


def hhmmss_to_insec(time_hhmmss):
    """Convert an HHMMSS-formatted time (e.g. 134502) to seconds since midnight.

    Direct port of hhmmss2insec.m. Values are treated as non-negative,
    matching the original's assumed domain (a time-of-day field). Every term is
    floored, seconds included (Octave: ``hhmmss2insec(120000.5)`` is 43200).
    """
    t = float(time_hhmmss)
    hh = t // 10000
    mm = (t % 10000) // 100
    ss = (t % 100) // 1
    return hh * 3600 + mm * 60 + ss


def insec_to_hhmmss(insec):
    """Convert seconds-since-midnight to HHMMSS format.

    Direct port of insec2hhmmss.m, every term floored (``insec2hhmmss(43200.5)``
    is 120000).
    """
    s = float(insec)
    hh = s // 3600
    mm = (s % 3600) // 60
    ss = (s % 60) // 1
    return hh * 10000 + mm * 100 + ss
