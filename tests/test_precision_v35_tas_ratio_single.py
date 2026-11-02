# SPDX-License-Identifier: BSD-3-Clause
"""``read_binary_SPEC.m:188`` -- ``tasRatio = imgTAS ./ fltTAS_fixed(...)``.

``imgTAS`` is a ``single`` (the packet's ``typecast(...,'single')``) and
``fltTAS_fixed`` a double, so MATLAB first narrows the double to ``single``
and divides in single arithmetic. Until pass 6 the port divided in double and
rounded the quotient to float32 once, which agrees only when the aircraft TAS
is exactly representable in float32. Measured under Octave 8.4 (pass 5,
item 4): ``single(123.4) ./ 131.7`` is ``0.9369780421257019``, the old port
value ``0.93697798252105713``; 4917 of 20000 random pairs differed, always by
one float32 ULP. ``arrayprobe_uiops.tas.tas_ratio`` now divides in float32.
"""

from __future__ import annotations

import unittest

import numpy as np

from arrayprobe_uiops.tas import tas_ratio

_OCTAVE_SINGLE_OVER_DOUBLE = 0.9369780421257019  # single(123.4) ./ 131.7, Octave 8.4


def _port_ratio(img_tas: float, flt_tas: float) -> float:
    """The exact expression ``spec.py:636`` applies to ``tas_ratio``'s result."""
    return float(np.float32(tas_ratio(img_tas, [100000.0], [flt_tas], 10, 0, 0)))


class TestSingleOverDoubleDivision(unittest.TestCase):
    def test_representable_aircraft_tas_agrees_with_octave(self):
        # 120 is exact in float32, so narrowing it first changes nothing:
        # 50/120 in single is the float32 neighbour, as spec.py's comment says.
        self.assertEqual(_port_ratio(50.0, 120.0), 0.4166666567325592)

    def test_unrepresentable_aircraft_tas_is_narrowed_first(self):
        # MATLAB: single(123.4) / single(131.7) in single arithmetic.
        self.assertEqual(_port_ratio(float(np.float32(123.4)), 131.7),
                         _OCTAVE_SINGLE_OVER_DOUBLE)

    def test_the_narrowed_operand_is_what_octave_computes(self):
        # The oracle value is reproduced by float32 / float32, not by a
        # double quotient rounded once: pins the reading of the Octave result.
        via_single = float(np.float32(123.4) / np.float32(131.7))
        via_double = float(np.float32(float(np.float32(123.4)) / 131.7))
        self.assertEqual(via_single, _OCTAVE_SINGLE_OVER_DOUBLE)
        self.assertNotEqual(via_double, _OCTAVE_SINGLE_OVER_DOUBLE)


if __name__ == "__main__":
    unittest.main()
