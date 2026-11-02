# SPDX-License-Identifier: BSD-3-Clause
"""Checks against the ORACLES reference data -- MATLAB output of record.

The files are large and not ours to redistribute, so they are gitignored and
these tests skip when they are absent.  They are the only end-to-end oracle the
project has (there is no MATLAB license), so what they *can* pin, they should.

Point ``ARRAYPROBE_REFERENCE_DATA`` at the tree to override the default location.

What is and is not an oracle here:

* ``old_oracles_data/2DS_H_current/base160906064017.combined.H.2DS_2.cdf`` and
  ``old_oracles_data/HVPS/base*.combined.V.HVPS_2.cdf`` -- **UIOOPS-variant output**,
  written by the ORACLES ``combine_sizedist`` step.  Real oracles, and the
  **products of record**: user-confirmed 2026-08-20 as the files behind the
  published research.
* ``old_oracles_data/2DS_H_old/base*.combined.H.2DS.cdf`` -- **SUPERSEDED, do not
  use.**  An earlier processing run of the same flight, kept on disk only so
  nothing is destroyed.  Same time axis and bin ladder, 38.7% of the accepted
  particles, differing in 6,466 of 28,815 seconds.
* ``old_oracles_data/2DS_H/*.conc.1Hz.nc`` -- **NOT UIOOPS**.  Global attributes name
  David Delene / University of North Dakota: these are ADPAA products from a
  different processing chain.  They do not fill the missing-output gap and must not be used as a
  header oracle, however much the filenames suggest otherwise.  Reconfirmed
  2026-08-20 on three more of them.
"""

import os
import unittest

import numpy as np
from tests._repo import repo_only

from arrayprobe import constants as C

try:
    from netCDF4 import Dataset
except ImportError:  # pragma: no cover
    Dataset = None

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT = os.path.abspath(os.path.join(
    _HERE, os.pardir, os.pardir, "arrayprobe-local-data", "old-stuff-data"
))
REFDIR = os.environ.get("ARRAYPROBE_REFERENCE_DATA", _DEFAULT)

COMBINED_2DS = os.path.join(
    REFDIR, "old_oracles_data", "2DS_H_current",
    "base160906064017.combined.H.2DS_2.cdf"
)
COMBINED_HVPS = os.path.join(
    REFDIR, "old_oracles_data", "HVPS", "base160906064017.combined.V.HVPS_2.cdf"
)

# The raw input for the same flight.
#
# PREFER THE UND DELIVERY. The five 09/06 files also sit loose at the repository
# root, and on 2026-09-01 they were shown to be byte-identical duplicates of the
# delivery copies (full SHA-256 on the smallest, 64 MB prefixes on the rest) --
# 4.5 GB of duplication that this default was what made load-bearing. The root
# copies are still accepted as a fallback so nothing breaks while the author
# decides whether to remove them; ARRAYPROBE_RAW_DATA overrides both.
_REPO = os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir))
_UND_0906 = os.path.join(_REPO, "arrayprobe-local-data", "2016-und-data", "20160906_1", "2DS_Data")
RAW_DIR = os.environ.get(
    "ARRAYPROBE_RAW_DATA",
    _UND_0906 if os.path.isdir(_UND_0906) else _REPO,
)
RAW_2DS = [
    "base160906064403.2DS",
    "base160906075333.2DS",
    "base160906095907.2DS",
    "base160906104932.2DS",
    "base160906125407.2DS",
]
RAW_HVPS = "base160906064343.HVPS"

#: The HVPS file is NOT in ``RAW_DIR``. The UND delivery separates the probes --
#: ``20160906_1/2DS_Data`` and ``20160906_1/HVPS3_Data`` -- and the guard below
#: looked for the ``.HVPS`` file in the 2D-S directory, so it skipped with
#: "raw ORACLES probe files not present" on a machine where the file was sitting
#: in the sibling directory the whole time. Found 2026-09-05 by enumerating the
#: suite's three skips instead of accepting the count.
_HVPS_SIBLING = os.path.join(os.path.dirname(RAW_DIR), "HVPS3_Data")
RAW_HVPS_DIR = (_HVPS_SIBLING
                if os.path.exists(os.path.join(_HVPS_SIBLING, RAW_HVPS))
                else RAW_DIR)


@unittest.skipUnless(os.path.exists(COMBINED_2DS), "ORACLES reference data not present")
class TestCombined2DS(unittest.TestCase):
    """The 09/06/2016 flight: five raw 2DS files combined into one output."""

    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset(COMBINED_2DS)

    @classmethod
    def tearDownClass(cls):
        cls.ds.close()

    def test_five_files_were_stitched(self):
        """Confirms the delivery's stated shape: 5 raw 2DS files -> 1 unified
        output at the final step. Reproducing this file therefore needs the
        variant's combine_PBP/combine_sizedist, which is why they sit on the
        validation critical path rather than at the interarrival or CLI stage."""
        self.assertEqual(len(self.ds.dimensions["files_stitched"]), 5)

    def test_flight_is_2016_so_horizontal_channel_only(self):
        """ORACLES 2016 flew the 2D-S horizontal channel only (the V-channel
        mirror was sooted); 2017 and 2018 flew both. The filename dates this
        flight to 2016, so one channel is in play, not two."""
        self.assertIn("base1609", os.path.basename(COMBINED_2DS))
        self.assertIn(".H.", os.path.basename(COMBINED_2DS))

    def test_bin_ladder_matches_the_transcribed_config(self):
        """constants.py's ('otherwise','2DS') case against MATLAB output.

        This is the first independent check of the config transcription: it
        confirms the ORACLES project falls through sizeDist.m:339 to `otherwise`,
        that num_bins is 128, that diodesize is 0.010 mm, and that the colon
        ladder `diodesize/2 : diodesize : (num_bins+0.6)*diodesize` terminates at
        1.285 mm exactly as MATLAB's does.
        """
        cfg = C.sizedist_config("ORACLES", "2DS")
        bin_min = np.asarray(self.ds["Bin Minimum"][:])
        bin_max = np.asarray(self.ds["Bin Maximum"][:])
        self.assertEqual(bin_min.size, cfg.num_bins)
        np.testing.assert_allclose(bin_min, cfg.kk[:-1], rtol=0, atol=1e-12)
        np.testing.assert_allclose(bin_max, cfg.kk[1:], rtol=0, atol=1e-12)

    def test_bin_width_matches(self):
        """sizeDist.m:523 -- binwidth = diff(kk)."""
        cfg = C.sizedist_config("ORACLES", "2DS")
        np.testing.assert_allclose(
            np.asarray(self.ds["Bin Width"][:]), cfg.binwidth, rtol=0, atol=1e-12
        )

    def test_output_is_netcdf3_classic(self):
        """The format is preserved bug-for-bug, 2 GiB ceiling and all."""
        self.assertEqual(self.ds.file_format, "NETCDF3_CLASSIC")

    def test_variable_names_contain_spaces(self):
        """'Bin Minimum', 'Size Distribution cm-3' -- part of the output contract,
        preserved verbatim rather than normalized to snake_case."""
        self.assertIn("Bin Minimum", self.ds.variables)
        self.assertIn("Size Distribution cm-3", self.ds.variables)


@unittest.skipUnless(os.path.exists(COMBINED_HVPS), "ORACLES reference data not present")
class TestCombinedHVPSDivergesFromStockUIOPS(unittest.TestCase):
    """The ORACLES HVPS run does NOT use stock UIOOPS's HVPS bin ladder.

    Stock ``sizeDist.m:341-364`` gives HVPS 28 hand-written bins out to 30 mm.
    The reference output has **70 uniform 0.15 mm bins** out to 10.575 mm -- the
    ``kk = diodesize/2 : diodesize : ...`` form that stock UIOOPS carries only as a
    commented-out alternative.  So the variant has its own probe configuration.

    These tests exist to stop a later stage from quietly binning ORACLES HVPS data
    with the stock ladder: the divergence is real, and it belongs in a
    ``FidelityProfile``, not in a patched shared table.
    """

    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset(COMBINED_HVPS)

    @classmethod
    def tearDownClass(cls):
        cls.ds.close()

    def test_reference_uses_seventy_uniform_bins(self):
        bin_min = np.asarray(self.ds["Bin Minimum"][:])
        widths = np.unique(np.round(np.asarray(self.ds["Bin Width"][:]), 9))
        self.assertEqual(bin_min.size, 70)
        self.assertEqual(widths.size, 1)
        self.assertAlmostEqual(float(widths[0]), 0.150)
        self.assertAlmostEqual(float(bin_min[0]), 0.075)   # diodesize/2

    def test_stock_config_would_disagree(self):
        """Named so the failure message says what it means if this ever passes."""
        stock = C.sizedist_config("ORACLES", "HVPS")
        self.assertEqual(stock.num_bins, 28)
        self.assertNotEqual(stock.num_bins, len(self.ds.dimensions["bin_count"]))

    def test_only_one_file_stitched_for_hvps(self):
        """The 5->1 combine is a 2DS-only feature of this flight."""
        self.assertEqual(len(self.ds.dimensions["files_stitched"]), 1)


class TestRawInputInventory(unittest.TestCase):
    """The end-to-end oracle needs raw input, not just reference output.

    Both branches of the plan rest on one premise: the five raw
    2D-S files for 09/06/2016 are on this machine, so the port can be run over
    them and its combined output compared against the MATLAB-written combined
    file. If that premise ever quietly stops holding -- files moved, archived,
    deleted to reclaim ~3.8 GB -- it should surface here rather than halfway
    through S2.
    """

    @unittest.skipUnless(
        os.path.exists(os.path.join(RAW_DIR, RAW_2DS[0])),
        "Raw ORACLES probe files are not distributed with the package",
    )
    def test_all_five_raw_2ds_files_are_present(self):
        """Five raw files, matching files_stitched=5 in the combined output."""
        missing = [n for n in RAW_2DS if not os.path.exists(os.path.join(RAW_DIR, n))]
        self.assertEqual(missing, [], f"raw 2D-S files missing from {RAW_DIR}")
        self.assertEqual(len(RAW_2DS), 5)

    @unittest.skipUnless(
        os.path.exists(os.path.join(RAW_DIR, RAW_2DS[0])),
        "Raw ORACLES probe files are not distributed with the package",
    )
    def test_raw_files_are_not_truncated(self):
        """Truncation would break value comparison silently. The three middle
        files sit exactly on the 2^30-byte SPEC file-size cap, which is what a
        complete rollover looks like; the first and last are partial by nature."""
        sizes = {n: os.path.getsize(os.path.join(RAW_DIR, n)) for n in RAW_2DS}
        for name, size in sizes.items():
            with self.subTest(file=name):
                self.assertGreater(size, 10_000_000)
        self.assertEqual(len({s for s in sizes.values() if s > 1_000_000_000}), 1)

    @unittest.skipUnless(
        os.path.exists(os.path.join(RAW_HVPS_DIR, RAW_HVPS)),
        "Raw ORACLES probe files are not distributed with the package",
    )
    def test_raw_hvps_is_present_and_single(self):
        """One raw HVPS file, matching files_stitched=1 on the HVPS side."""
        self.assertTrue(os.path.exists(os.path.join(RAW_HVPS_DIR, RAW_HVPS)))

    @repo_only
    def test_raw_files_are_gitignored(self):
        """These are not public and must never be committed. The .gitignore
        patterns are the safety net against `git add -A`; this asserts they still
        cover the actual filenames."""
        gitignore = os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir, ".gitignore"))
        if not os.path.exists(gitignore):
            self.skipTest("no .gitignore (running outside a checkout)")
        with open(gitignore, encoding="utf-8") as fh:
            patterns = {ln.strip() for ln in fh}
        self.assertIn("*.2DS", patterns)
        self.assertIn("*.HVPS", patterns)
        self.assertIn("old-stuff-data/", patterns)
        self.assertIn("arrayprobe-local-data/", patterns)


if __name__ == "__main__":
    unittest.main()
