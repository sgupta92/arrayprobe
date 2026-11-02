# SPDX-License-Identifier: BSD-3-Clause
"""The stratified validation, which had no test until 2026-09-10.

It answers the author's own 2026-08-28 ask -- check the port *"on multiple
samples, in and out of cloud, and over different conditions"* -- and until this
file every number it produced went straight into a ``print`` inside
a script, so nothing could assert on any of it. The
arithmetic now lives in :mod:`arrayprobe.validate_by_condition`; these are its
first assertions.

The property worth protecting is not the arithmetic, which is sums. It is
**which file decides the band**. Condition must come from the REFERENCE's
per-second total, because using ours would make the stratification depend on
the thing being tested: a second we under-count would be filed as sparser than
it really was, and the sparse band would then flatter us with a second that
belongs in the dense one. That is a mistake which makes the report look better
while making it wrong, so it gets a test that fails if the sides are swapped.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

from arrayprobe.ncio import _quiet_netcdf4_setitem
from arrayprobe.validate_by_condition import (
    BANDS,
    PRODUCT_DIR_ENV,
    find_product,
    parse_hhmmss,
    resolve_product_dir,
    stratify,
)

#: An arbitrary MATLAB datenum for midnight; only differences matter.
_DAY = 736000.0


def _write(path, counts, second_offsets):
    """A combined-product-shaped file: `Time Vector` datenums and `Counts`.

    ``counts`` is (bins, time). Only the two variables `stratify` reads are
    written -- a fuller fixture would suggest the function reads more than it
    does.
    """
    bins, n = counts.shape
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("Time", n)
        ds.createDimension("bin_count", bins)
        tv = ds.createVariable("Time Vector", "f8", ("Time",))
        tv[:] = _DAY + np.asarray(second_offsets, float) / 86400.0
        c = ds.createVariable("Counts", "f8", ("bin_count", "Time"))
        # netCDF4 reshapes the array in place on assignment, which
        # NumPy 2.5 deprecates -- the package's own helper for this.
        with _quiet_netcdf4_setitem():
            c[:, :] = counts


@unittest.skipIf(netCDF4 is None, "netCDF4 not installed")
class Stratifying(unittest.TestCase):
    #: 128, not a convenient small number. `_counts_of` decides which axis is
    #: bins by looking for a length of 128, so a 10-bin fixture is silently
    #: TRANSPOSED and every second's total becomes a bin's total -- which is
    #: how the first draft of this file put all four of its seconds in one
    #: band. The assumption is correct for every real product and is now
    #: stated in the module; the fixture has to honour it.
    BINS = 128

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _pair(self, ours, ref, seconds=None):
        seconds = list(range(ours.shape[1])) if seconds is None else seconds
        a, b = self.tmp / "ours.cdf", self.tmp / "ref.cdf"
        _write(a, ours, seconds)
        _write(b, ref, seconds)
        return str(a), str(b)

    def _flat(self, per_second):
        """(bins, time), with each second's total spread over the bins."""
        out = np.zeros((self.BINS, len(per_second)))
        for i, total in enumerate(per_second):
            out[:, i] = total / self.BINS
        return out

    def test_an_identical_pair_agrees_everywhere(self):
        counts = self._flat([0, 50, 500, 9000])
        st = stratify(*self._pair(counts, counts), drop_bins=0)
        self.assertEqual(st.shared_seconds, 4)
        self.assertEqual(st.overall.exact_seconds, 4)
        self.assertEqual(st.overall.all_ours, st.overall.all_ref)

    def test_each_second_lands_in_the_band_its_total_names(self):
        # One second per band, at totals that are unambiguous inside it.
        counts = self._flat([0, 50, 500, 9000])
        st = stratify(*self._pair(counts, counts), drop_bins=0)
        self.assertEqual([b.label for b in st.bands], [b[2] for b in BANDS])
        for band in st.bands:
            self.assertEqual(band.seconds, 1, band.label)

    def test_the_band_boundaries_are_inclusive_lower_exclusive_upper(self):
        """1, 100 and 5000 are boundaries; each belongs to the band above."""
        counts = self._flat([1, 100, 5000])
        st = stratify(*self._pair(counts, counts), drop_bins=0)
        labels = [b.label for b in st.bands]
        self.assertNotIn(BANDS[0][2], labels, "0 is the ONLY clear total")
        self.assertEqual(len(labels), 3)

    def test_condition_comes_from_the_reference_not_from_ours(self):
        """The property the whole design rests on.

        One second: the reference says 9,000 particles (dense), we found 3. If
        the band were taken from ours it would be filed sparse. Filing it
        sparse is the failure that makes a bad result read as a good one.
        """
        ref = self._flat([9000])
        ours = self._flat([3])
        st = stratify(*self._pair(ours, ref), drop_bins=0)
        self.assertEqual([b.label for b in st.bands], ["dense   (>5k/s)"])
        self.assertEqual(st.bands[0].all_ref, 9000)
        self.assertEqual(st.bands[0].all_ours, 3)

    def test_a_band_with_no_seconds_is_omitted_rather_than_reported_empty(self):
        counts = self._flat([50, 60])
        st = stratify(*self._pair(counts, counts), drop_bins=0)
        self.assertEqual([b.label for b in st.bands], ["sparse  (1-100/s)"])

    def test_overall_is_computed_over_the_mask_not_summed_from_the_bands(self):
        """Documented on `Stratification.overall`, and true here by construction.

        With every band populated the two happen to agree, so this asserts the
        agreement -- the point being that `overall` must be right even when a
        band is omitted, which the previous test covers from the other side.
        """
        counts = self._flat([0, 50, 500, 9000])
        st = stratify(*self._pair(counts, counts), drop_bins=0)
        self.assertEqual(st.overall.seconds, sum(b.seconds for b in st.bands))
        self.assertAlmostEqual(st.overall.all_ref,
                               sum(b.all_ref for b in st.bands))

    def test_drop_bins_excludes_the_low_bins_from_the_used_columns(self):
        ours = np.zeros((self.BINS, 1))
        ours[:, 0] = 1.0          # one particle in every bin
        st = stratify(*self._pair(ours, ours), drop_bins=4)
        self.assertEqual(st.overall.all_ours, self.BINS)
        self.assertEqual(st.overall.used_ours, self.BINS - 4)
        self.assertEqual(st.drop_bins, 4)

    def test_only_shared_seconds_are_compared(self):
        ours = self._flat([50, 50, 50])
        ref = self._flat([50, 50])
        a, b = self.tmp / "o.cdf", self.tmp / "r.cdf"
        _write(a, ours, [10, 11, 12])
        _write(b, ref, [11, 12])
        st = stratify(str(a), str(b), drop_bins=0)
        self.assertEqual(st.shared_seconds, 2)

    def test_a_window_restricts_the_comparison(self):
        counts = self._flat([50] * 4)
        # Seconds 0..3 of the day; the window covers 000001-000003.
        st = stratify(*self._pair(counts, counts, seconds=[0, 1, 2, 3]),
                      window="000001-000003", drop_bins=0)
        self.assertEqual(st.shared_seconds, 4)
        self.assertEqual(st.window_seconds, 2)
        self.assertEqual(st.overall.seconds, 2)

    def test_counts_stored_time_major_are_transposed(self):
        """`Counts` is (bins, time) in some files and (time, bins) in others.

        The reader picks by which axis is 128, so a fixture with 128 bins is
        the only way to exercise the real branch.
        """
        n = 3
        # np.ones((n, 128)) is what netCDF4 reshapes in place and NumPy
        # 2.5 deprecates; build it the shape it is written in.
        counts = np.ones((n, 128), dtype=np.float64)
        a, b = self.tmp / "o.cdf", self.tmp / "r.cdf"
        for path in (a, b):
            with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
                ds.createDimension("Time", n)
                ds.createDimension("bin_count", 128)
                tv = ds.createVariable("Time Vector", "f8", ("Time",))
                tv[:] = _DAY + np.arange(n) / 86400.0
                c = ds.createVariable("Counts", "f8", ("Time", "bin_count"))
                with _quiet_netcdf4_setitem():
                    c[:, :] = counts.copy()
        st = stratify(str(a), str(b), drop_bins=0)
        self.assertEqual(st.shared_seconds, n)
        self.assertEqual(st.overall.all_ours, n * 128)

    def test_nan_counts_are_read_as_zero(self):
        counts = self._flat([50])
        counts[0, 0] = np.nan
        st = stratify(*self._pair(counts, counts), drop_bins=0)
        self.assertFalse(np.isnan(st.overall.all_ours))


class Helpers(unittest.TestCase):
    def test_hhmmss_is_parsed_as_a_clock_time_not_a_number(self):
        self.assertEqual(parse_hhmmss("000000"), 0)
        self.assertEqual(parse_hhmmss("010203"), 3600 + 120 + 3)
        self.assertEqual(parse_hhmmss("235959"), 86399)

    def test_find_product_matches_on_the_date_not_the_whole_stem(self):
        """A product's stem is the flight's summary-file timestamp and ours is
        a raw file's, so they agree on the date and generally not the time."""
        with tempfile.TemporaryDirectory() as tmp:
            product = Path(tmp) / "base160906064017.combined.H.2DS_2.cdf"
            product.touch()
            found = find_product("base160906064403.combined.H.2DS_2.cdf", tmp)
            self.assertEqual(found, str(product))

    def test_find_product_returns_none_rather_than_guessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "base160906064017.combined.H.2DS_2.cdf").touch()
            self.assertIsNone(find_product("base160910071400.x.cdf", tmp))
            self.assertIsNone(find_product("no-date-here.cdf", tmp))


class ProductDirResolution(unittest.TestCase):
    """The products directory is named by the caller or by one environment variable,
    used exactly as given: the package assumes no folder layout beneath it."""

    def test_explicit_directory_wins_over_the_environment(self):
        with mock.patch.dict(os.environ, {PRODUCT_DIR_ENV: "/from/env"}):
            self.assertEqual(resolve_product_dir("/explicit"), "/explicit")

    def test_environment_directory_is_used_as_given_with_no_subfolder_appended(self):
        with mock.patch.dict(os.environ, {PRODUCT_DIR_ENV: "/some/products"}):
            self.assertEqual(resolve_product_dir(None), "/some/products")

    def test_neither_given_is_a_clear_error_not_a_guess(self):
        env = {k: v for k, v in os.environ.items() if k != PRODUCT_DIR_ENV}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValueError) as cm:
                resolve_product_dir(None)
            self.assertIn(PRODUCT_DIR_ENV, str(cm.exception))
            self.assertIn("--product-dir", str(cm.exception))

    def test_find_product_reads_the_environment_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            product = Path(tmp) / "base160906064017.combined.H.2DS_2.cdf"
            product.touch()
            with mock.patch.dict(os.environ, {PRODUCT_DIR_ENV: tmp}):
                self.assertEqual(
                    find_product("base160906064403.combined.H.2DS_2.cdf"), str(product))

    def test_the_module_text_names_no_data_folder_layout(self):
        src = Path(resolve_product_dir.__code__.co_filename)
        text = src.read_text(encoding="utf-8")
        self.assertNotIn("old_oracles" + "_data", text)
        self.assertNotIn("ARRAYPROBE_REFERENCE" + "_DATA", text)


if __name__ == "__main__":
    unittest.main()
