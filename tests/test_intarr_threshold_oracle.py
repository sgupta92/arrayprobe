# SPDX-License-Identifier: BSD-3-Clause
"""S8b's threshold selection, against a real Octave run of the source itself.

`IntArrAnalysis_time.m` computes three thresholds per population and writes exactly one of them
(``threshhold_ak``, `:363`). A known gap: the fit underneath cannot be bit-exact: MATLAB's
robust `nlinfit` has no equivalent with matching semantics, and Octave's own `nlinfit` silently
drops `'Robust'`. That is true, and it is why `threshold` (``min(tau(1:2))*2``) differs here by up
to ~20 %.

**But the value the source actually writes does not depend on the fit that closely.**
``threshhold_ak = newDT(indexOriginal)`` is the bin centre where the *observed* histogram is
lowest inside ``(min(tau), max(tau))`` — the histogram is identical input, and the window is wide
enough that a small change in `tau` does not move which bin is the global minimum. Measured on
five real populations of `base160906064403`, the port and Octave agree on ``threshold_ak``
**exactly, 5 of 5**, while their `tau` values differ throughout.

So this test pins the part that *can* be exact against the original, and bounds the part
that cannot. Written after the driver was first run on real data (2026-08-29) and its output
looked surprising.
The fixture is tracked, so this runs with no Octave installed.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from arrayprobe.intarr_analysis import HIST_BINS, block_thresholds

try:  # scipy is an *extra* (pip install "arrayprobe[extra]"), not a core dependency:
    import scipy  # noqa: F401   the package must install with no toolchain.
    _HAS_SCIPY = True
except ImportError:                     # pragma: no cover - depends on the env
    _HAS_SCIPY = False


from pathlib import Path as _P  # noqa: E402

# _release_fixture_guard: s8_intarr_threshold_octave_golden.json is excluded from the release
if not (_P(__file__).resolve().parent / "data" / "s8_intarr_threshold_octave_golden.json").exists():
    raise unittest.SkipTest(
        "needs a stored reference result that this release does not distribute")


def setUpModule():
    """Skip, rather than error, when the optional fit dependency is absent.

    `intarr.py` imports scipy lazily inside the fitting function, so the module
    imports fine and the failure surfaced only when a test called it. On the
    author's laptop scipy has always been in the venv, so this path had never
    been taken; the first clean-environment CI run (2026-09-08) turned it into
    34 errors across the port and enhancement suites. An optional dependency
    that is absent must skip with a message, not raise.
    """
    if not _HAS_SCIPY:
        raise unittest.SkipTest(
            "scipy is not installed; it is an extra (pip install \"arrayprobe[extra]\") "
            "and the interarrival fits need it")


_GOLDEN = Path(__file__).parent / "data" / "s8_intarr_threshold_octave_golden.json"

#: `threshold` is a direct function of the fitted tau, so it inherits the gap fully. The observed
#: spread across these five blocks is 6-20 %; 30 % bounds it without being vacuous.
_FIT_TOLERANCE = 0.30


class ThresholdSelectionAgainstOctave(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(_GOLDEN.read_text(encoding="utf-8"))
        cls.blocks = cls.doc["blocks"]

    def _port(self, block):
        return block_thresholds(np.asarray(block["counts"], dtype=float))

    def test_the_written_threshold_is_exact_on_every_block(self):
        """`threshhold_ak` is the only value `:363` writes -- and it is oracle-exact."""
        for i, block in enumerate(self.blocks, start=1):
            with self.subTest(block=i):
                _, _, ak, _ = self._port(block)
                self.assertAlmostEqual(
                    ak, block["octave_threshold_ak"], places=12,
                    msg=f"block {i}: the written threshold no longer matches the Octave run")

    def test_the_written_threshold_is_a_real_histogram_bin_centre(self):
        """It is selected from `binsCenter`, never interpolated -- so it must be one of them."""
        centres = HIST_BINS[:-1] + np.diff(HIST_BINS) / 2
        for i, block in enumerate(self.blocks, start=1):
            with self.subTest(block=i):
                _, _, ak, _ = self._port(block)
                self.assertTrue(np.any(np.isclose(centres, ak, rtol=1e-12)),
                                f"block {i}: {ak!r} is not a bin centre")

    def test_the_fitted_threshold_stays_within_one_bin_of_octave(self):
        """`_ww` reads the *fitted* curve, so the fit gap can move it -- but only by a bin."""
        centres = HIST_BINS[:-1] + np.diff(HIST_BINS) / 2
        for i, block in enumerate(self.blocks, start=1):
            with self.subTest(block=i):
                _, ww, _, _ = self._port(block)
                here = int(np.argmin(np.abs(centres - ww)))
                there = int(np.argmin(np.abs(centres - block["octave_threshold_ww"])))
                self.assertLessEqual(abs(here - there), 1,
                                     f"block {i}: _ww moved {abs(here - there)} bins from Octave")

    def test_the_tau_derived_threshold_is_close_but_not_claimed_exact(self):
        """The fit gap made explicit as a bound rather than left as prose."""
        for i, block in enumerate(self.blocks, start=1):
            with self.subTest(block=i):
                thr, _, _, _ = self._port(block)
                ref = block["octave_threshold"]
                self.assertLessEqual(abs(thr - ref) / ref, _FIT_TOLERANCE,
                                     f"block {i}: min(tau)*2 drifted further from Octave "
                                     "than the measured fitting tolerance allows")

    def test_the_written_threshold_sits_far_above_the_per_probe_default(self):
        """B9's substance, pinned: this is the source's behaviour, not a port artefact.

        Every block's written threshold is orders of magnitude above the 6 microsecond per-probe
        default `sizeDist.m` falls back to. If a change ever makes these look ordinary, the
        finding needs re-measuring, not the test relaxing.
        """
        for i, block in enumerate(self.blocks, start=1):
            with self.subTest(block=i):
                _, _, ak, _ = self._port(block)
                self.assertGreater(ak, 100 * 6e-6,
                                   f"block {i}: written threshold {ak:.3e} is no longer >100x "
                                   f"the 6 us default -- re-measure B9")


if __name__ == "__main__":
    unittest.main()
