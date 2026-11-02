# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe.validation_report`` -- typed results for the same comparison
the combined-product validation gate prints."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np
from tests._repo import needs_file  # noqa: E402

from arrayprobe.validation_report import compare_to_product

VAR = "Counts"


def _write(path, seconds, values, bins_last=False):
    """A minimal combined-product-shaped file: ``Time Vector`` (MATLAB
    datenum, one whole second apart) and ``Counts`` over (bins, time) --
    or (time, bins) when ``bins_last``, to exercise the orientation guess.
    """
    n_bins, n_time = values.shape
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", n_time)
        ds.createDimension("bin", n_bins)
        base = 738000.0  # an arbitrary MATLAB datenum
        tv = ds.createVariable("Time Vector", "f8", ("time",))
        tv[:] = base + np.asarray(seconds, dtype=float) / 86400.0
        if bins_last:
            v = ds.createVariable(VAR, "f8", ("time", "bin"))
            v[:] = values.T
        else:
            v = ds.createVariable(VAR, "f8", ("bin", "time"))
            v[:] = values


class TwoDenominators(unittest.TestCase):
    """Exact agreement: both denominators read 100%, no residual seconds."""

    def test_identical_files_agree_on_both_denominators(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            values = np.array([[0, 0, 1, 2],
                                [0, 1, 0, 3],
                                [np.nan, 0, 0, 0]])
            _write(tmp / "ours.cdf", [0, 1, 2, 3], values)
            _write(tmp / "ref.cdf", [0, 1, 2, 3], values)

            report = compare_to_product(str(tmp / "ours.cdf"), str(tmp / "ref.cdf"), drop=1)

            self.assertEqual(report.shared_seconds, 4)
            self.assertEqual(report.uncovered_ref_seconds, 0)
            self.assertEqual(report.uncovered_ours_seconds, 0)
            self.assertEqual(report.residual_seconds, ())

            all_bins = report.cell(VAR, "all bins")
            self.assertEqual(all_bins.non_zero_pct, 100.0)
            self.assertEqual(all_bins.both_present_pct, 100.0)

            used = report.cell(VAR, "used bins 2-128")
            self.assertEqual(used.non_zero_pct, 100.0)
            # bin 0 dropped; both_zero counts cells where both sides are 0
            # among the remaining bins/seconds that are both non-NaN.
            self.assertGreaterEqual(used.both_zero_n, 0)

    def test_a_real_disagreement_is_named_by_second_and_excluded_from_zero_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            ours = np.array([[1, 2, 3, 4]], dtype=float)
            ref = np.array([[1, 2, 30, 4]], dtype=float)  # second index 2 disagrees
            _write(tmp / "ours.cdf", [10, 11, 12, 13], ours)
            _write(tmp / "ref.cdf", [10, 11, 12, 13], ref)

            report = compare_to_product(str(tmp / "ours.cdf"), str(tmp / "ref.cdf"), drop=0)

            self.assertEqual(report.residual_seconds, (12,))
            cell = report.cell(VAR, "used bins 1-128")
            self.assertEqual(cell.non_zero_n, 4)
            self.assertEqual(cell.non_zero_agree, 3)
            self.assertEqual(cell.both_zero_n, 0)

    def test_both_zero_is_excluded_from_the_non_zero_denominator_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            values = np.array([[0.0, 5.0]])
            _write(tmp / "ours.cdf", [0, 1], values)
            _write(tmp / "ref.cdf", [0, 1], values)

            report = compare_to_product(str(tmp / "ours.cdf"), str(tmp / "ref.cdf"), drop=0)
            cell = report.cell(VAR, "used bins 1-128")
            # both cells present and equal; one is the 0==0 cell excluded from
            # the strict (non-zero) denominator but not from both-present.
            self.assertEqual(cell.both_present_n, 2)
            self.assertEqual(cell.both_present_agree, 2)
            self.assertEqual(cell.both_zero_n, 1)
            self.assertEqual(cell.non_zero_n, 1)
            self.assertEqual(cell.non_zero_agree, 1)

    def test_a_missing_shared_second_is_reported_as_coverage_not_disagreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write(tmp / "ours.cdf", [0, 1, 2], np.array([[1.0, 2.0, 3.0]]))
            _write(tmp / "ref.cdf", [1, 2, 3], np.array([[2.0, 3.0, 9.0]]))

            report = compare_to_product(str(tmp / "ours.cdf"), str(tmp / "ref.cdf"), drop=0)

            self.assertEqual(report.shared_seconds, 2)  # seconds 1, 2
            self.assertEqual(report.uncovered_ref_seconds, 1)  # ref's second 3
            self.assertEqual(report.uncovered_ours_seconds, 1)  # ours' second 0

    def test_orientation_is_detected_not_assumed(self):
        """``(time, bin)`` storage must be read identically to ``(bin, time)``.

        Needs bin count != time count -- the orientation guess (shared with
        ``validate_combined_product.py``) compares shape against ``n_time``,
        which cannot disambiguate a square array.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            values = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])  # (bin=2, time=3)
            _write(tmp / "ours.cdf", [0, 1, 2], values, bins_last=False)
            _write(tmp / "ref.cdf", [0, 1, 2], values, bins_last=True)

            report = compare_to_product(str(tmp / "ours.cdf"), str(tmp / "ref.cdf"), drop=0)
            cell = report.cell(VAR, "used bins 1-128")
            self.assertEqual(cell.non_zero_pct, 100.0)

    def test_missing_variable_on_one_side_is_skipped_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with netCDF4.Dataset(tmp / "ours.cdf", "w", format="NETCDF3_CLASSIC") as ds:
                ds.createDimension("time", 1)
                ds.createDimension("bin", 1)
                ds.createVariable("Time Vector", "f8", ("time",))[:] = [738000.0]
                ds.createVariable(VAR, "f8", ("bin", "time"))[:] = [[1.0]]
            with netCDF4.Dataset(tmp / "ref.cdf", "w", format="NETCDF3_CLASSIC") as ds:
                ds.createDimension("time", 1)
                ds.createDimension("bin", 1)
                ds.createVariable("Time Vector", "f8", ("time",))[:] = [738000.0]
                # No "Counts" on this side, and no "Size Distribution cm-3" either.

            report = compare_to_product(str(tmp / "ours.cdf"), str(tmp / "ref.cdf"), drop=0)
            self.assertEqual(report.cells, ())


class GateAndReportAgree(unittest.TestCase):
    """The library's verdict and the gate's exit code are the same fact.

    ``compare_to_product`` reports a used-bin non-zero percentage; the
    combined-product validation gate exits 1 when that percentage is below
    100 and 0 when it is exactly 100. Two tools reading the same pair must not
    disagree on whether it passed.
    """

    def _gate(self, ours, ref, drop):
        import importlib.util
        import io
        from contextlib import redirect_stdout
        tools = Path(__file__).resolve().parent.parent / "scripts"
        spec = importlib.util.spec_from_file_location(
            "validate_combined_product", tools / "validate_combined_product.py")
        vcp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vcp)
        with redirect_stdout(io.StringIO()):
            return vcp.main([str(ours), "--product", str(ref), "--drop-bins", str(drop)])

    @needs_file("scripts/validate_combined_product.py")
    def test_pass_and_fail_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            ref = np.array([[1.0, 2.0, 3.0, 4.0]])
            _write(tmp / "ref.cdf", [10, 11, 12, 13], ref)
            for name, ours, want_rc in (("same.cdf", ref.copy(), 0),
                                        ("diff.cdf", np.array([[1.0, 2.0, 30.0, 4.0]]), 1)):
                _write(tmp / name, [10, 11, 12, 13], ours)
                report = compare_to_product(str(tmp / name), str(tmp / "ref.cdf"), drop=0)
                exact = report.cell(VAR, "used bins 1-128").non_zero_pct == 100.0
                rc = self._gate(tmp / name, tmp / "ref.cdf", 0)
                self.assertEqual(rc, want_rc, name)
                self.assertEqual(rc == 0, exact, name)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
