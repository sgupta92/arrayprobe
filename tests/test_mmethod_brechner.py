# SPDX-License-Identifier: BSD-3-Clause
"""``mmethod`` on ``arrayprobe_uiops.sizedist.run``/``._run`` and the ported
``arrayprobe_uiops.mass_b26`` it delegates to for ``mmethod`` 1-3.

Folded into ``arrayprobe_uiops`` on 2026-09-17 (no new packages).
Until that day this module was ``arrayprobe_v35_brechner``, a sibling
package; the code, the dispatch and every test below are unchanged by the
move -- only the import path is (``from arrayprobe_uiops.mass_b26 import ...``
in place of ``from arrayprobe_v35_brechner import ...``).

Two states, both tested:

* **Default (``mmethod`` omitted, or 0)** must be bit-identical to the code
  path that existed before ``mmethod`` did -- :class:`TestDefaultIsBitIdentical`.
* **Opt-in (``mmethod`` 1, 2 or 3)** reaches ``arrayprobe_uiops.mass_b26`` and
  is exercised end-to-end on a synthetic fixture carrying the
  ``Holroyd_perimeter`` variable stock v3.5 fixtures do not --
  :class:`TestMmethodDispatchEndToEnd`.

``arrayprobe_uiops.mass_b26`` itself is checked against a hand computation of
``massB26.m:1-13`` in :class:`TestMassB26Formula` -- the oracle used
elsewhere in this project (Octave, the real v3.5 goldens) does not reach this
file at all, since it is not part of either vendored tree; see that module's
docstring for the ``file:line`` citations into the gitignored source box.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np

from arrayprobe_uiops import sizedist as v35s

try:  # not in the public release: the method is unpublished (held back 2026-10-16)
    from arrayprobe_uiops.mass_b26 import mass_b26, particle_mass_dispatch
except ImportError:
    mass_b26 = particle_mass_dispatch = None

needs_mass_b26 = unittest.skipIf(
    mass_b26 is None,
    "Arrayprobe_uiops.mass_b26 is not distributed with the package",
)

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
PROC_FIXTURE = DATA / "v35_sizedist_synthetic.proc.nc"

TAS = np.array([170.0, 170.0, 180.0, 170.0, 170.0, 170.0])
TIMES = np.array([120001.0, 120002.0, 120003.0, 120004.0, 120005.0, 120006.0])
PRES = np.full(6, 9e5)
TEMP = np.full(6, 15.0)
DDATE = "20151205 120002"
SOFTWARE = "UIOOPS_v3.5"
CREATION_TIME = "2026/09/12 01:19:41"


@needs_mass_b26
class TestMassB26Formula(unittest.TestCase):
    """``massB26.m:1-13``, hand-computed for one particle."""

    def test_uncalibrated_pow_branch(self):
        # A = 0.05 mm^2, D = 0.3 mm, P = 1.2 mm, ds = 0.010 mm (a 2D-S).
        area, diameter, perimeter, ds = 0.05, 0.3, 1.2, 0.010
        f_obs = diameter * perimeter / area  # :7
        pow_ = (ds / 0.008) ** 0.3  # :9, since pow==0
        f_use = 4 * (f_obs / 4) ** pow_  # :11
        a_over_p = diameter / f_use  # :12
        expected = (8 / 3) * 0.91e-3 * area * a_over_p  # :13

        got = mass_b26(np.array([area]), np.array([diameter]),
                        np.array([perimeter]), np.array([ds]), pow=0.0)
        np.testing.assert_allclose(got, [expected], rtol=1e-12)

    def test_nonzero_pow_skips_the_calibration_branch(self):
        # :8-10 -- `if pow == 0` is a scalar test; pow=1 must NOT be
        # recomputed from diodesize.
        area, diameter, perimeter, ds = 0.05, 0.3, 1.2, 0.010
        f_obs = diameter * perimeter / area
        f_use = 4 * (f_obs / 4) ** 1.0
        a_over_p = diameter / f_use
        expected = (8 / 3) * 0.91e-3 * area * a_over_p

        got = mass_b26(np.array([area]), np.array([diameter]),
                        np.array([perimeter]), np.array([ds]), pow=1.0)
        np.testing.assert_allclose(got, [expected], rtol=1e-12)


@needs_mass_b26
class TestParticleMassDispatch(unittest.TestCase):
    def test_mmethod_1_baker_lawson(self):
        # sizeDist_decibel3.m:1192-1194
        area = np.array([0.01, 0.05])
        expected = 0.115 / 1000 * area ** 1.218
        got = particle_mass_dispatch(1, area=area, particle_diameter_minR=None)
        np.testing.assert_allclose(got, expected)

    def test_mmethod_2_brown_and_francis(self):
        # sizeDist_decibel3.m:1195-1197
        diam = np.array([0.2, 0.5])
        expected = 0.00294 * (diam / 10) ** 1.9
        got = particle_mass_dispatch(2, area=None, particle_diameter_minR=diam)
        np.testing.assert_allclose(got, expected)

    def test_mmethod_3_needs_holroyd_perimeter(self):
        with self.assertRaises(ValueError):
            particle_mass_dispatch(
                3, area=np.array([0.05]), particle_diameter_minR=np.array([0.3]),
                mass_diameter_minR=np.array([0.3]),
            )

    def test_mmethod_3_hollow_correction_uses_the_smaller_perimeter(self):
        # sizeDist_decibel3.m:1209: for auto_reject == 'h', HP is capped at
        # the outer (image_perimeter) value when that is smaller.
        area = np.array([0.05])
        diam = np.array([0.3])
        big_hp = np.array([5.0])
        small_outer = np.array([1.2])
        capped = particle_mass_dispatch(
            3, area=area, particle_diameter_minR=diam, mass_diameter_minR=diam,
            holroyd_perimeter=big_hp, outer_perimeter=small_outer,
            hollow_mask=np.array([True]), diodesize=np.array([0.01]),
        )
        uncapped = particle_mass_dispatch(
            3, area=area, particle_diameter_minR=diam, mass_diameter_minR=diam,
            holroyd_perimeter=big_hp, outer_perimeter=small_outer,
            hollow_mask=np.array([False]), diodesize=np.array([0.01]),
        )
        # A smaller perimeter (:12, AovP = D/F_use) with F_use held down by a
        # bigger F_obs is not monotonic in one direction in general, but the
        # two calls MUST disagree -- the mask is what changed.
        self.assertFalse(np.allclose(capped, uncapped))

    def test_unknown_mmethod_rejected(self):
        with self.assertRaises(ValueError):
            particle_mass_dispatch(4, area=None, particle_diameter_minR=None)


def _add_dummy_holroyd_perimeter(src: Path, dst: Path) -> None:
    shutil.copy(src, dst)
    with netCDF4.Dataset(dst, "a") as ds:
        # A synthetic, plausible Holroyd perimeter: 1.4x image_perimeter,
        # clear of the values `image_perimeter` itself holds so the two
        # never accidentally agree and mask a wiring bug.
        perim = np.asarray(ds.variables["image_perimeter"][:])
        v = ds.createVariable("Holroyd_perimeter", "f8", ("time",))
        v[:] = perim * 1.4


class TestDefaultIsBitIdentical(unittest.TestCase):
    """``mmethod`` omitted and ``mmethod=0`` must run the identical code
    path -- the doctrine's "no arithmetic changes because a call came
    through" requirement, here for the new keyword rather than a selector
    module."""

    def setUp(self):
        if not PROC_FIXTURE.is_file():
            self.skipTest(f"proc fixture missing: {PROC_FIXTURE}")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_omitted_matches_explicit_zero(self):
        out_omitted = Path(self._tmp.name) / "omitted.nc"
        out_zero = Path(self._tmp.name) / "zero.nc"
        common = dict(
            software=SOFTWARE, creation_time=CREATION_TIME,
        )
        v35s.run(str(PROC_FIXTURE), str(out_omitted), TAS, TIMES, "2DS", 6, 0,
                 PRES, TEMP, 0, 0, 1, 1, "ORACLES", DDATE, **common)
        v35s.run(str(PROC_FIXTURE), str(out_zero), TAS, TIMES, "2DS", 6, 0,
                 PRES, TEMP, 0, 0, 1, 1, "ORACLES", DDATE, mmethod=0, **common)
        with netCDF4.Dataset(out_omitted) as a, netCDF4.Dataset(out_zero) as b:
            names_a, names_b = set(a.variables), set(b.variables)
            self.assertEqual(names_a, names_b)
            for name in sorted(names_a):
                va = np.asarray(a.variables[name][:])
                vb = np.asarray(b.variables[name][:])
                # Bit-identical, not merely close -- np.array_equal treats
                # NaN as unequal by default, so compare the finite mask too.
                self.assertTrue(
                    np.array_equal(va, vb, equal_nan=True), f"{name} differs"
                )


@needs_mass_b26
class TestMmethodDispatchEndToEnd(unittest.TestCase):
    """``mmethod=3`` run through the real driver on a fixture carrying
    ``Holroyd_perimeter`` -- stock v3.5 fixtures never do, since only
    Peter Brechner's fork reads that variable."""

    def setUp(self):
        if not PROC_FIXTURE.is_file():
            self.skipTest(f"proc fixture missing: {PROC_FIXTURE}")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_mmethod_3_changes_mass_and_runs_end_to_end(self):
        fixture = Path(self._tmp.name) / "with_holroyd.nc"
        _add_dummy_holroyd_perimeter(PROC_FIXTURE, fixture)
        out_default = Path(self._tmp.name) / "default.nc"
        out_brechner = Path(self._tmp.name) / "brechner.nc"
        common = dict(software=SOFTWARE, creation_time=CREATION_TIME)

        v35s.run(str(fixture), str(out_default), TAS, TIMES, "2DS", 6, 0,
                 PRES, TEMP, 0, 0, 1, 1, "ORACLES", DDATE, **common)
        v35s.run(str(fixture), str(out_brechner), TAS, TIMES, "2DS", 6, 0,
                 PRES, TEMP, 0, 0, 1, 1, "ORACLES", DDATE, mmethod=3, **common)

        with netCDF4.Dataset(out_default) as a, netCDF4.Dataset(out_brechner) as b:
            mass_default = np.asarray(a.variables["mass"][:])
            mass_brechner = np.asarray(b.variables["mass"][:])
            finite = np.isfinite(mass_default) & np.isfinite(mass_brechner)
            self.assertTrue(finite.any(), "no finite mass-bin values to compare")
            self.assertFalse(
                np.allclose(mass_default[finite], mass_brechner[finite]),
                "mmethod=3 produced the same mass as the habit M-D default",
            )

    def test_missing_holroyd_perimeter_raises_a_named_netcdf_error(self):
        # PROC_FIXTURE has no Holroyd_perimeter -- asking for mmethod=3
        # against it must fail loudly, not silently fall back to mmethod=0.
        # `ncio`'s `inq_var_id` raises KeyError naming the missing variable.
        out_path = Path(self._tmp.name) / "out.nc"
        with self.assertRaises(KeyError):
            v35s.run(str(PROC_FIXTURE), str(out_path), TAS, TIMES, "2DS", 6, 0,
                     PRES, TEMP, 0, 0, 1, 1, "ORACLES", DDATE, mmethod=3,
                     software=SOFTWARE, creation_time=CREATION_TIME)

if __name__ == "__main__":
    unittest.main()
