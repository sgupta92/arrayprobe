# SPDX-License-Identifier: BSD-3-Clause
"""Table 9-2's published bounds, and the two computed consequences of them."""

from __future__ import annotations

import unittest

from arrayprobe_enhancements.probe_uncertainty import (
    IMAGING_UNCERTAINTY,
    LIGHT_SCATTERING_UNCERTAINTY,
    shape_floor_diameter_um,
    vaillant_de_guelis_envelope,
)


class TheTableItself(unittest.TestCase):
    def test_imaging_bounds_are_table_9_2_verbatim(self):
        self.assertEqual(IMAGING_UNCERTAINTY.size_pct, (10.0, 100.0))
        self.assertEqual(IMAGING_UNCERTAINTY.concentration_pct, (10.0, 100.0))
        self.assertEqual(IMAGING_UNCERTAINTY.shape_min_pixels, (5.0, 12.0))

    def test_light_scattering_cannot_derive_shape(self):
        self.assertIsNone(LIGHT_SCATTERING_UNCERTAINTY.shape_min_pixels)
        self.assertEqual(LIGHT_SCATTERING_UNCERTAINTY.size_pct, (10.0, 50.0))
        self.assertEqual(LIGHT_SCATTERING_UNCERTAINTY.concentration_pct, (10.0, 30.0))

    def test_the_range_is_never_narrowed_to_a_point(self):
        """The published table gives a range; this module must never collapse
        it to a single invented number."""
        lo, hi = IMAGING_UNCERTAINTY.size_pct
        self.assertLess(lo, hi)


class ShapeFloorDiameter(unittest.TestCase):
    def test_the_2ds_ten_micron_resolution_gives_fifty_to_one_twenty(self):
        self.assertEqual(shape_floor_diameter_um(10.0), (50.0, 120.0))

    def test_a_coarser_probe_scales_linearly(self):
        # HVPS, 150 um resolution (config/HVPS.ini, per this project's own
        # SPIF-source reading -- see SPIF_INTEROP.md).
        self.assertEqual(shape_floor_diameter_um(150.0), (750.0, 1800.0))

    def test_a_caller_supplied_pixel_range_overrides_the_default(self):
        self.assertEqual(shape_floor_diameter_um(10.0, pixels=(1.0, 2.0)), (10.0, 20.0))


class VaillantDeGuelisEnvelope(unittest.TestCase):
    def test_the_measured_columnar_band_returns_its_published_bound(self):
        self.assertEqual(vaillant_de_guelis_envelope(130.0), (-23.0, 35.0))

    def test_the_measured_large_circular_band_returns_its_published_bound(self):
        self.assertEqual(vaillant_de_guelis_envelope(1000.0), (-10.0, 10.0))
        self.assertEqual(vaillant_de_guelis_envelope(806.0), (-10.0, 10.0))

    def test_outside_both_measured_bands_is_honestly_none(self):
        """Between 159.6 and 806 um, and below 112.8 um, nothing was measured
        -- interpolating a curve through the two bands would be exactly the
        kind of invented fact this module's docstring refuses."""
        self.assertIsNone(vaillant_de_guelis_envelope(400.0))
        self.assertIsNone(vaillant_de_guelis_envelope(50.0))


if __name__ == "__main__":
    unittest.main()
