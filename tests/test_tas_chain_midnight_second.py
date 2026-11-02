# SPDX-License-Identifier: BSD-3-Clause
"""The TAS chain across midnight: fixed under the midnight convention, UIOOPS's unwrapped
24xxxx-hours convention
(decided 2026-09-28).

Pass-5 item 9, 2026-09-26, found two disagreeing halves of the same module. A probe
``.tas.csv`` row at 235959.5 or later is keyed to second 86400 by ``whole_second_series``
(``make_tas_file.py:365``, ``round``) and by ``tas_sources._probe_seconds`` (``:247``),
written as HHMMSS 240000 -- the probe side already keeps counting past midnight rather than
wrapping. But ``check_tas_series``'s clock check (``make_tas_file.py:255``) refused anything
past 235959 as "probably seconds since some epoch", and ``read_aircraft`` folded its own time
axis back to 000000 at 86400 s (``tas_sources.py:187``/``:196``, ``np.mod(..., 86400)``) -- so
the probe tier, the aircraft tier (which extends its series over the probe's rounded seconds)
and ``make-tas-file --from-tas-csv`` all failed or silently disagreed with the probe's own
clock for a flight whose housekeeping runs past midnight.

**Fixed 2026-09-28, unwrapped, not wrapped**: ``check_tas_series`` now accepts an hour of
24-47 (one further midnight crossing -- the same span ``sizeDist.m:98-99``'s ``+240000``
rollover, ``arrayprobe.sizedist._rollover_240000``, produces for particle times) as a valid
clock hour, so it no longer refuses 240000 and later; ``read_aircraft`` no longer folds its
time axis back to 0 at 86400 s, so an aircraft file whose clock also runs unwrapped past
midnight is read as such, matching the probe side instead of disagreeing with it. Nothing
here is engine code -- both fixes are in ``python_port/tools``/``src/arrayprobe/tools``,
never a faithful port path.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe.tools import make_tas_file as mtf
from arrayprobe.tools import tas_sources as ts


def _probe_csv(rows):
    d = Path(tempfile.mkdtemp())
    p = d / "p.tas.csv"
    p.write_text("".join(f"{t}, {v}, 0, 0, 0, 0, 0, 0, 0\n" for t, v in rows))
    return d, p


class MidnightRoundingToday(unittest.TestCase):
    """The probe side's own unwrapped rounding, unchanged by the fix."""

    def test_probe_seconds_key_235959_7_to_240000(self):
        _, p = _probe_csv([(235958.2, 100.0), (235959.7, 100.0)])
        np.testing.assert_array_equal(ts._probe_seconds(p), [235958.0, 240000.0])

    def test_regular_grid_crosses_midnight_as_the_probe_clock_does(self):
        g = ts.regular_grid_hhmmss([235958.3, 235959.9, 0.4, 1.2])
        np.testing.assert_array_equal(g, [235958.0, 235959.0, 0.0, 1.0])


class MidnightNoLongerRefused(unittest.TestCase):
    """B5 fixed: 240000 and later are accepted as a clock time, and the aircraft side no
    longer wraps to disagree with the probe side. Each test failed before the fix (see the
    module docstring for exactly how); running them now proves it."""

    def test_check_tas_series_accepts_240000(self):
        t, v = mtf.check_tas_series([235959.0, 240000.0], [100.0, 100.0])
        np.testing.assert_array_equal(t, [235959.0, 240000.0])

    def test_check_tas_series_still_refuses_a_bad_minute_or_second(self):
        with self.assertRaisesRegex(ValueError, "not a clock time"):
            mtf.check_tas_series([240060.0], [100.0])   # minute 60 is never valid
        with self.assertRaisesRegex(ValueError, "not a clock time"):
            mtf.check_tas_series([991234.0], [100.0])   # hour 99: still read as an epoch value

    def test_aircraft_side_no_longer_wraps_seconds_of_day(self):
        # read_aircraft's own conversion (tas_sources.py:187) is exercised end to end in
        # test_aircraft_tier_extends_over_a_probe_second_at_midnight below; this pins the
        # underlying formula it now uses (make_tas_file._sod_to_hhmmss, unwrapped).
        np.testing.assert_array_equal(
            mtf._sod_to_hhmmss(np.array([86399, 86400, 86401])),
            [235959.0, 240000.0, 240001.0])

    def test_probe_tier_accepts_a_csv_whose_last_row_rounds_to_midnight(self):
        d, p = _probe_csv([(235958.2, 100.0), (235959.7, 100.0)])
        res = ts.resolve_chain("probe", yyyymmdd=None, probe_csv=p)
        ts.write_chain_file(d / "chain.cdf", res)
        self.assertIn(240000.0, res.time.tolist())

    def test_aircraft_tier_extends_over_a_probe_second_at_midnight(self):
        d, p = _probe_csv([(235958.2, 100.0), (235959.7, 100.0)])
        ac = d / "ac.cdf"
        mtf.write_tas_file(ac, [235957.0, 235958.0], [110.0, 111.0])
        res = ts.resolve_chain("aircraft", yyyymmdd=None, probe_csv=p,
                               explicit={"aircraft": str(ac)})
        ts.write_chain_file(d / "chain.cdf", res)
        self.assertEqual(res.time.max(), 240000.0)


if __name__ == "__main__":
    unittest.main()
