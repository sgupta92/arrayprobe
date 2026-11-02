# SPDX-License-Identifier: BSD-3-Clause
"""The batch driver's post-S4 plausibility gate: an empty or near-empty sd built from a
proc that accepted particles is refused (kept on disk, stamped IMPLAUSIBLE), unless
--accept-implausible, which the stamp records. The plausibility token never makes two stamps
differ; the override marker does."""
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe.driver import run_flight as rf


def _write_sd(path: Path, conc: np.ndarray) -> None:
    """A minimal sd: Time and conc_minR declared MATLAB-style, so the file holds (bins, Time)."""
    nsec, nbins = conc.shape
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("Time", nsec)
        ds.createDimension("Vector28", nbins)
        ds.createVariable("Time", "f8", ("Time",))[:] = 100000 + np.arange(nsec)
        ds.createVariable("conc_minR", "f8", ("Vector28", "Time"))[:] = conc.T


def _write_proc(path: Path, accepted: int) -> None:
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("pos", accepted + 3)
        v = ds.createVariable("image_auto_reject", "f8", ("pos",))
        # Three rejects: 'a' (97, aspect ratio). Not 'h' (104): sizeDist accepts "0HhuR", so a
        # hollow particle is kept and would be counted as accepted.
        v[:] = np.r_[np.full(accepted, 48.0), np.full(3, 97.0)]


class S4PlausibilityGate(unittest.TestCase):
    def setUp(self):
        self._saved = (rf.ACCEPT_IMPLAUSIBLE, rf.log)
        rf.ACCEPT_IMPLAUSIBLE = False
        self.logged = []
        rf.log = self.logged.append
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.proc = self.d / "x.proc.cdf"
        _write_proc(self.proc, 500)

    def tearDown(self):
        rf.ACCEPT_IMPLAUSIBLE, rf.log = self._saved
        self.tmp.cleanup()

    def _gate(self, conc):
        sd = self.d / "x.sd.cdf"
        _write_sd(sd, conc)
        stamp, why = rf._s4_plausibility_gate(sd, self.proc, "engine=3.5 iat=NONE")
        self.assertTrue(sd.exists(), "the gate must never delete the sd")
        return stamp, why

    def test_fires_on_an_all_zero_sd(self):
        stamp, why = self._gate(np.zeros((3600, 28)))
        self.assertIsNotNone(why)
        self.assertIn("IMPLAUSIBLE)", stamp)
        self.assertIn("accepted=500", stamp)
        self.assertIn("time_offset", why)
        self.assertIn("bin table", why)

    def test_fires_on_a_near_empty_28_bin_sd(self):
        conc = np.zeros((20000, 28))
        conc[5, 3] = 1.0  # one second in 20,000: 0.005 %, under the 0.1 % threshold
        stamp, why = self._gate(conc)
        self.assertIsNotNone(why)
        self.assertIn("bins=28", stamp)

    def test_passes_a_normal_sd(self):
        conc = np.zeros((3600, 28))
        conc[::10, 2:6] = 5.0
        stamp, why = self._gate(conc)
        self.assertIsNone(why)
        self.assertIn(",ok)", stamp)
        self.assertTrue(stamp.startswith("engine=3.5 iat=NONE plausibility=("))

    def test_warns_but_passes_on_nonfinite_and_duplicated_seconds(self):
        conc = np.zeros((3600, 28))
        conc[::10, 2:6] = 5.0
        conc[7, 0] = np.inf
        conc[8, 1] = 1.7976931348623157e308
        sd = self.d / "x.sd.cdf"
        _write_sd(sd, conc)
        with netCDF4.Dataset(sd, "a") as ds:
            t = ds.variables["Time"][:]
            t[1] = t[0]
            ds.variables["Time"][:] = t
        stamp, why = rf._s4_plausibility_gate(sd, self.proc, "engine=3.5")
        self.assertIsNone(why)
        self.assertIn("nonfinite=2,dup=1", stamp)
        self.assertTrue(any("WARNING" in m for m in self.logged))

    def test_override_keeps_the_sd_and_is_stamped(self):
        rf.ACCEPT_IMPLAUSIBLE = True
        stamp, why = self._gate(np.zeros((3600, 28)))
        self.assertIsNone(why)
        self.assertIn("IMPLAUSIBLE)", stamp)
        saved_engine = rf.ENGINE
        self.addCleanup(setattr, rf, "ENGINE", saved_engine)
        rf.ENGINE = "3.5"  # the gate, and its override marker, are engine-3.5 only
        self.assertIn(rf.ACCEPT_IMPLAUSIBLE_STAMP, rf.sd_call_label(None))
        rf.ENGINE = "3.1.4"  # the archived-record engine never carries the marker
        self.assertNotIn(rf.ACCEPT_IMPLAUSIBLE_STAMP, rf.sd_call_label(None))
        rf.ENGINE = "3.5"
        rf.ACCEPT_IMPLAUSIBLE = False
        self.assertNotIn(rf.ACCEPT_IMPLAUSIBLE_STAMP, rf.sd_call_label(None))

    def test_passes_a_short_sparse_valid_flight(self):
        """500 accepted particles in 5 distinct seconds of a 20,000-second axis; the sd carries
        particles in 4 of them (0.02 % of the axis, under 0.1 %): measured against the proc's
        accepted seconds, not the axis, so it passes."""
        with netCDF4.Dataset(self.proc, "a") as ds:
            ds.createVariable("particle_time", "f8", ("pos",))[:] = (
                100000 + np.repeat([10, 11, 12, 13, 14], 101)[:503] + 0.25)
        conc = np.zeros((20000, 28))
        conc[[10, 11, 12, 13], 3] = 1.0
        stamp, why = self._gate(conc)
        self.assertIsNone(why)
        self.assertIn(",ok)", stamp)

    def test_passes_an_empty_sd_from_a_handful_of_accepted_particles(self):
        """The demo flight's case: 3 accepted particles that sizeDist's own rejections drop."""
        _write_proc(self.proc, 3)
        stamp, why = self._gate(np.zeros((600, 28)))
        self.assertIsNone(why)
        self.assertIn("accepted=3,ok)", stamp)

    def test_unreadable_sd_is_warned_not_refused(self):
        sd = self.d / "x.sd.cdf"
        sd.write_bytes(b"")
        stamp, why = rf._s4_plausibility_gate(sd, self.proc, "engine=3.5")
        self.assertIsNone(why)
        self.assertEqual(stamp, "engine=3.5")  # no measurement, no token
        self.assertTrue(sd.exists())

    def test_refusal_is_its_own_exception_class(self):
        self.assertTrue(issubclass(rf.ImplausibleProduct, rf.UnverifiableProvenance))


class StampEquivalence(unittest.TestCase):
    def test_plausibility_token_never_makes_stamps_differ(self):
        base = "engine=3.5 iat=NONE"
        tok = "plausibility=(sec=10,pos=0.5000,nonfinite=0,dup=0,bins=28,accepted=5,ok)"
        self.assertTrue(rf._stamps_equivalent(f"{base} {tok}", base))
        self.assertTrue(rf._stamps_equivalent(base, f"{base} {tok}"))

    def test_override_marker_does(self):
        base = "engine=3.5 iat=NONE"
        self.assertFalse(rf._stamps_equivalent(f"{base} {rf.ACCEPT_IMPLAUSIBLE_STAMP}", base))


if __name__ == "__main__":
    unittest.main()
