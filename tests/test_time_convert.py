# SPDX-License-Identifier: BSD-3-Clause
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from time_convert import hhmmss_to_insec, insec_to_hhmmss


class TestTimeConvert(unittest.TestCase):
    def test_hand_computed_values(self):
        # 13:45:02 -> 13*3600 + 45*60 + 2 = 46800 + 2700 + 2 = 49502
        self.assertEqual(hhmmss_to_insec(134502), 49502)
        self.assertEqual(insec_to_hhmmss(49502), 134502)

    def test_midnight(self):
        self.assertEqual(hhmmss_to_insec(0), 0)
        self.assertEqual(insec_to_hhmmss(0), 0)

    def test_last_second_of_day(self):
        # 23:59:59 -> 86399 seconds
        self.assertEqual(hhmmss_to_insec(235959), 86399)
        self.assertEqual(insec_to_hhmmss(86399), 235959)

    def test_noon(self):
        self.assertEqual(hhmmss_to_insec(120000), 43200)
        self.assertEqual(insec_to_hhmmss(43200), 120000)

    def test_round_trip_hhmmss_start(self):
        # Every valid HHMMSS in the day, sampled every 137s, must survive
        # a full round trip through both functions.
        h, m, s = 0, 0, 0
        insec = 0
        while insec < 86400:
            hhmmss = h * 10000 + m * 100 + s
            self.assertEqual(insec_to_hhmmss(hhmmss_to_insec(hhmmss)), hhmmss)
            insec += 137
            h = insec // 3600
            m = (insec % 3600) // 60
            s = insec % 60

    def test_round_trip_insec_start(self):
        for insec in range(0, 86400, 149):
            self.assertEqual(hhmmss_to_insec(insec_to_hhmmss(insec)), insec)


if __name__ == "__main__":
    unittest.main()
