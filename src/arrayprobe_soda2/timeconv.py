# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""The driver's two small time-conversion
leaves, `hms2sfm.pro` (12 lines) and `soda2_parsedate.pro` (22 lines), ported
whole -- no round-7 cut in either.

Vendored source: `SODA2/abansemer-soda2-afcea15/hms2sfm.pro`,
`soda2_parsedate.pro`. Bank: `gdl_oracle/run_soda2_preloop_bank.py`, golden
`tests/data/gdl_soda2_preloop_golden.json`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .spec_index import julday


def hms2sfm(hms: float | int | np.floating) -> float:
    """`hms2sfm.pro:6-11`: seconds-from-midnight for an `HHMMSS[.f]`-packed
    time. `long(hms)` truncates toward zero; `fraction = double(hms) -
    long(hms)` widens `hms` to DOUBLE first -- for a FLOAT32 input that
    widening carries float32 rounding error into the DOUBLE result, so a
    `np.float32` argument is widened via `float(np.float32(x))`, never via a
    fresh Python `float(x)` on the original value. The whole expression is
    DOUBLE because `fraction` is DOUBLE (T9: truncation toward zero, so
    `hms2sfm(-1)` truncates to 0, not -1)."""
    if isinstance(hms, np.floating) and hms.dtype == np.float32:
        widened = float(hms)  # numpy widens float32 -> python float (== double) faithfully
    else:
        widened = float(hms)
    def _idiv(a: int, b: int) -> int:
        """IDL LONG division truncates toward zero, unlike Python `//`."""
        q = a // b
        if q < 0 and q * b != a:
            q += 1
        return q

    ihms = int(widened) if widened >= 0 else -int(-widened)  # long(): truncate toward zero
    fraction = widened - ihms
    hour = _idiv(ihms, 10000)
    minute = _idiv(ihms - hour * 10000, 100)
    second = ihms - hour * 10000 - minute * 100
    return float(hour * 3600 + minute * 60 + second) + fraction


@dataclass
class ParsedDate:
    """The structure ``soda2_parsedate.pro:20`` (SODA-2) returns, one field per IDL tag."""
    year: str
    month: str
    day: str
    yearnum: int
    monthnum: int
    daynum: int
    order: str
    julday: int


def soda2_parsedate(date: str) -> ParsedDate:
    """`soda2_parsedate.pro:6-21`. The year-first test is on the first two
    characters of `date` being `'19'` or `'20'`; the other order is assumed
    otherwise (MMDDYYYY). `julday` is called with the three **string**
    fields (`:19`), which the bank's `pd_*` cases pin -- `julday()` here
    takes them straight through `int()` per the golden, not assumed."""
    s = str(date)
    if s[0:2] in ("19", "20"):
        year, month, day = s[0:4], s[4:6], s[6:8]
        order = "ymd"
    else:
        month, day, year = s[0:2], s[2:4], s[4:8]
        order = "mdy"
    yearnum, monthnum, daynum = int(year), int(month), int(day)
    jd = julday(monthnum, daynum, yearnum)
    return ParsedDate(year=year, month=month, day=day, yearnum=yearnum,
                       monthnum=monthnum, daynum=daynum, order=order, julday=jd)
