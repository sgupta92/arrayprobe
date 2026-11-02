# SPDX-License-Identifier: BSD-3-Clause
"""``imgproc_sm_v35(jit=True)`` writes the same bytes as ``jit=False`` --
the v3.5 counterpart of ``test_imgproc_jit_identity.py``.

Space: the port. The jit path is speed only, so the whole claim is identity,
and a byte-identical claim is a test, not a sentence.
Each S3 run here is
made twice, once each way, with ``creation_time`` pinned -- the one
non-deterministic attribute -- and the two ``proc`` files are compared
**byte for byte**, then variable by variable so a failure names what moved.

**Input, and why this file rather than a synthetic fixture.** The real
production CIP S2 output this port already validates against,
``_decoded/cip160906/sea_s1.CIP.cdf`` (gitignored -- every class here skips
cleanly when it is absent), run with the exact production call recorded at
``_decoded/cip160906/v35_prod/proc.sea_s1.CIP.nc.call``
(``iRectEllipse=0, iCalcAllDiodeStats=0, iQC=0, iNewHabit=0, tas_ratio=off``).
That call is what the jit-kernel profiling ran against
(``arrayprobe_uiops/jit_kernels.py``'s module docstring), and real CIP cloud
data is dense enough that the first 30 records alone carry over a thousand
particles through ``measure.py:1218-1236``'s ``[EXPERIMENTAL]`` hollow
override (small ``minR``, habit forced to ``'s'``) --
``JitIsByteIdentical.test_the_window_exercises_the_rewritten_hollow_path``
measures this directly rather than assuming a hand-built image would reach
it, since that override lives in code this module does not accelerate (see
``jit_kernels.py``) and the byte-identity claim must still hold across it.

**What is actually being proven here.** ``arrayprobe_uiops.jit_kernels``
reuses v3.1.4's already-compiled, already-proven kernels rather than
recompiling new ones (see its module docstring), so the exactness of
``particle_perimeter`` and ``dec2bin_concat`` themselves is
``test_imgproc_jit_identity.py``'s claim, not this file's. What is new here,
and load-bearing: that ``imgproc_sm_v35`` reaches those same kernels
correctly from its own call sites, and that the runtime monkeypatch onto
``arrayprobe_uiops.measure`` (the only way to reach ``particle_perimeter``
inside ``measure_record`` without editing a file outside this change's
scope -- see ``imgproc.py``'s ``_patched_measure_perimeter``) applies
during the call and never leaks outside it.
"""

from __future__ import annotations

import filecmp
import inspect
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

try:
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

try:
    import numba  # noqa: F401 -- presence test only
    HAVE_NUMBA = True
except ImportError:  # pragma: no cover
    HAVE_NUMBA = False

from arrayprobe.profiles import ORACLES_PRODUCTION_V35
from arrayprobe_uiops.imgproc import imgproc_sm_v35

REPO = Path(__file__).resolve().parents[1]

#: The real production CIP S2 output the jit-kernel profiling ran against.
#: Gitignored (a raw archive product kept outside the repository), so
#: every class below skips cleanly rather than failing when it is absent.
REAL_CIP = REPO / "_decoded" / "cip160906" / "sea_s1.CIP.cdf"

FIXED_CREATION_TIME = "2000/01/01 00:00:00"

#: The real production call for this file, verbatim from
#: ``_decoded/cip160906/v35_prod/proc.sea_s1.CIP.nc.call``.
_CALL_KWARGS = dict(
    iRectEllipse=0, iCalcAllDiodeStats=0, iQC=0, iNewHabit=0,
    reject_config=ORACLES_PRODUCTION_V35.reject_thresholds,
    tas_time=None, tas=None, tas_ratio=None,
    software="UIOOPS_v3.5", creation_time=FIXED_CREATION_TIME,
)


def run_s3(out, jit, n_records):
    """One whole-window ``imgproc_sm_v35`` call, the real production call."""
    return imgproc_sm_v35(str(REAL_CIP), str(out), "CIP", 1, n_records, "ORACLES",
                          jit=jit, **_CALL_KWARGS)


def payload_differences(path_a, path_b) -> list[str]:
    """Every way two ``proc`` files differ; empty means identical.

    The byte comparison is the claim; the per-variable pass exists so a
    failure says which variable moved. Mirrors
    ``test_imgproc_jit_identity.py``'s helper of the same name.
    """
    diffs = []
    if not filecmp.cmp(path_a, path_b, shallow=False):
        diffs.append("file bytes differ")
    with netCDF4.Dataset(str(path_a)) as a, netCDF4.Dataset(str(path_b)) as b:
        if list(a.variables) != list(b.variables):
            diffs.append("variable set or order differs")
        for name in a.variables:
            if name not in b.variables:
                continue
            va, vb = a.variables[name], b.variables[name]
            if va.dtype != vb.dtype:
                diffs.append(f"{name}: dtype")
            xa, xb = np.asarray(va[:]), np.asarray(vb[:])
            if xa.shape != xb.shape or xa.tobytes() != xb.tobytes():
                diffs.append(f"{name}: values")
        for attr in a.ncattrs():
            if getattr(a, attr) != getattr(b, attr, None):
                diffs.append(f"@{attr}")
    return diffs


@unittest.skipIf(netCDF4 is None or not HAVE_NUMBA, "needs netCDF4 and numba")
@unittest.skipUnless(REAL_CIP.is_file(),
                     f"CIP raw file not distributed with the package: {REAL_CIP}")
class JitIsByteIdentical(unittest.TestCase):
    """The claim: jit=True and jit=False write the same bytes, on real CIP data."""

    N_RECORDS = 30

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.ref = Path(cls._tmp.name) / "ref.nc"
        cls.fast = Path(cls._tmp.name) / "fast.nc"
        cls.n_ref = run_s3(cls.ref, jit=False, n_records=cls.N_RECORDS)
        cls.n_fast = run_s3(cls.fast, jit=True, n_records=cls.N_RECORDS)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_particle_counts_agree(self):
        self.assertGreater(self.n_ref, 0, "the input must yield particles")
        self.assertEqual(self.n_ref, self.n_fast)

    def test_every_variable_and_every_byte_agrees(self):
        self.assertEqual(payload_differences(self.ref, self.fast), [])

    def test_the_window_exercises_the_rewritten_hollow_path(self):
        """``measure.py:1218-1236``'s ``[EXPERIMENTAL]`` override (new in v3.5,
        not accelerated by this change -- see ``jit_kernels.py``) forces habit
        ``'s'`` whenever ``minR*diodesize < 0.3`` and the centre window has an
        unshadowed pixel. Confirms the byte-identity claim above actually
        covers particles that took that branch, rather than happening to
        avoid it."""
        with netCDF4.Dataset(str(self.ref)) as ds:
            minr = np.asarray(ds.variables["image_diam_minR"][:])
            habit = np.asarray(ds.variables["holroyd_habit"][:])
        n = int(((habit == ord("s")) & (minr < 0.3)).sum())
        self.assertGreater(n, 0, "this window never exercised the hollow override; "
                                 "widen N_RECORDS")


@unittest.skipIf(netCDF4 is None or not HAVE_NUMBA, "needs netCDF4 and numba")
@unittest.skipUnless(REAL_CIP.is_file(),
                     f"CIP raw file not distributed with the package: {REAL_CIP}")
class TheIdentityCheckFires(unittest.TestCase):
    """Break one kernel by one unit; the file comparison must see it.

    A guard must be executed, not read (this machine's own standing lesson).
    Run on a short window (8 records) rather than ``JitIsByteIdentical``'s 30,
    so the mutation tests stay fast.
    """

    N_RECORDS = 8

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.ref = Path(cls._tmp.name) / "ref.nc"
        run_s3(cls.ref, jit=False, n_records=cls.N_RECORDS)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_a_perimeter_off_by_one_is_reported(self):
        from arrayprobe_uiops import jit_kernels
        k = jit_kernels.load()
        real = k.particle_perimeter
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.nc"
            with mock.patch.object(k, "particle_perimeter", lambda c: real(c) + 1):
                run_s3(bad, jit=True, n_records=self.N_RECORDS)
            diffs = payload_differences(self.ref, bad)
        self.assertIn("file bytes differ", diffs)
        self.assertIn("image_perimeter: values", diffs)

    def test_a_dec2bin_concat_bit_flip_is_reported(self):
        from arrayprobe_uiops import jit_kernels
        k = jit_kernels.load()
        real = k.dec2bin_concat

        def bad(columns, width):
            out = np.array(real(columns, width), copy=True)
            if out.size:
                out.flat[0] = out.flat[0] ^ 1  # toggles ascii '0' (48) <-> '1' (49)
            return out

        with tempfile.TemporaryDirectory() as tmp:
            bad_path = Path(tmp) / "bad.nc"
            with mock.patch.object(k, "dec2bin_concat", bad):
                run_s3(bad_path, jit=True, n_records=self.N_RECORDS)
            diffs = payload_differences(self.ref, bad_path)
        self.assertIn("file bytes differ", diffs)


class KernelsAreReusedNotRecopied(unittest.TestCase):
    """``arrayprobe_uiops.jit_kernels`` must not carry a second, unproven
    translation of a function v3.1.4 already accelerates and tests."""

    @unittest.skipUnless(HAVE_NUMBA, "needs numba")
    def test_v35_kernels_are_the_same_objects_as_v314s(self):
        from arrayprobe import jit_kernels as v314
        from arrayprobe_uiops import jit_kernels as v35
        k314 = v314.load()
        k35 = v35.load()
        # dec2bin_concat is stored as a plain function reference (JitKernels.__init__
        # does `self.dec2bin_concat = dec2bin_concat`), so the attribute itself is
        # the same object across both wrappers.
        self.assertIs(k35.dec2bin_concat, k314.dec2bin_concat)
        # particle_perimeter is a `def` on the class, so every attribute access
        # creates a fresh bound-method wrapper (`obj.meth is obj.meth` is False in
        # general) -- what must be identical is the underlying function AND the
        # wrapped instance, i.e. that v35 reused the SAME compiled JitKernels
        # object v3.1.4 uses, not a second one.
        self.assertIs(k35.particle_perimeter.__func__, k314.particle_perimeter.__func__)
        self.assertIs(k35.particle_perimeter.__self__, k314.particle_perimeter.__self__)


class ThePatchIsScopedAndFailsLoudly(unittest.TestCase):
    """``imgproc.py``'s ``_patched_measure_perimeter`` is the mechanism that
    reaches ``measure_record``'s call without editing ``measure.py``. It must
    never leak past the call it serves, and it must never silently no-op --
    that silent no-op is the exact shape of the original defect."""

    def test_none_kernels_is_a_no_op(self):
        from arrayprobe_uiops import imgproc as m
        from arrayprobe_uiops import measure as measure_mod
        original = measure_mod.particle_perimeter
        with m._patched_measure_perimeter(None):
            self.assertIs(measure_mod.particle_perimeter, original)
        self.assertIs(measure_mod.particle_perimeter, original)

    def test_restored_after_normal_exit(self):
        from arrayprobe_uiops import imgproc as m
        from arrayprobe_uiops import measure as measure_mod

        class FakeKernels:
            @staticmethod
            def particle_perimeter(c):
                return 0

        original = measure_mod.particle_perimeter
        with m._patched_measure_perimeter(FakeKernels()):
            self.assertIs(measure_mod.particle_perimeter, FakeKernels.particle_perimeter)
        self.assertIs(measure_mod.particle_perimeter, original)

    def test_restored_after_an_exception(self):
        from arrayprobe_uiops import imgproc as m
        from arrayprobe_uiops import measure as measure_mod

        class FakeKernels:
            @staticmethod
            def particle_perimeter(c):
                return 0

        original = measure_mod.particle_perimeter
        with self.assertRaises(ZeroDivisionError):
            with m._patched_measure_perimeter(FakeKernels()):
                raise ZeroDivisionError
        self.assertIs(measure_mod.particle_perimeter, original)

    def test_a_missing_target_raises_instead_of_silently_skipping(self):
        from arrayprobe_uiops import imgproc as m
        from arrayprobe_uiops import measure as measure_mod

        class FakeKernels:
            @staticmethod
            def particle_perimeter(c):
                return 0

        original = measure_mod.particle_perimeter
        del measure_mod.particle_perimeter
        try:
            with self.assertRaises(AttributeError):
                with m._patched_measure_perimeter(FakeKernels()):
                    pass  # pragma: no cover -- must not be reached
        finally:
            measure_mod.particle_perimeter = original


class TheOptInIsOffAndLazy(unittest.TestCase):
    def test_jit_defaults_off(self):
        self.assertIs(inspect.signature(imgproc_sm_v35).parameters["jit"].default, False)

    def test_importing_imgproc_does_not_import_the_jit_module(self):
        """numba costs seconds to import; the opt-in module loads on
        request, in a fresh process so no earlier test's import leaks in."""
        code = ("import sys, arrayprobe_uiops.imgproc; "
                "print('arrayprobe_uiops.jit_kernels' in sys.modules, "
                "'numba' in sys.modules)")
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             env=env, timeout=120, check=True)
        self.assertEqual(out.stdout.strip(), "False False")


if __name__ == "__main__":
    unittest.main()
