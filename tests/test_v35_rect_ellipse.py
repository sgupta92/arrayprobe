# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_uiops.rect_ellipse`` -- v3.5's ``iRectEllipse=1`` unit (Part D).

Three validation layers, in the order this file uses them:

1. **Pinned real-MEX values** (:class:`TestPinnedMexValues`) -- the exact
   ``CGAL_RectSize``/``CGAL_EllipseSize`` numbers measured directly against
   the compiled binaries (``octave_oracle/mex_build/README.md``'s smoke
   test), independent of the whole-chain bank.
2. **The whole-chain Octave golden** (:class:`TestTheGoldenIsWhatItClaims`,
   :class:`TestAgainstTheOctaveGolden`) -- ``octave_oracle/run_v35_rect_ellipse_bank.py``
   runs the real, unmodified v3.5 ``imgProc_sm.m`` against a purpose-built
   NON-degenerate fixture, through both real ``CGAL_EllipseSize`` binaries.
3. **Layer 3, stated**: :class:`TestDegenerateImagesDoNotAbortThePort` runs
   the port on the EXISTING (degenerate-on-purpose) ``imgProc_sm.m`` driver fixture, where the
   real MATLAB/Octave binary would abort the interpreter (A16) and cannot be
   goldened at all.

**Two things measured 2026-09-13 that shape every tolerance below, and why
neither is a Part-D-specific "fudge":**

* **CGAL's ``Min_ellipse_2`` is a randomized incremental algorithm.** Major
  and minor axis LENGTHS are stable across repeated fresh-process runs on
  identical input (measured: 8/8 identical, every fixture particle, both
  MEX binaries) -- the minimum enclosing ellipse is mathematically unique,
  so this is expected. The ANGLE is not: for a particle whose minimum
  enclosing ellipse is a circle (major == minor, by 4-fold or reflective
  symmetry of the shadowed pixels -- ``square_4``, ``ring_7_3``,
  ``edge_square`` and the group's ``_square(60, 3)``/``_ring(70, 5, 2)`` in
  this bank's own fixture), the angle output was measured to differ between
  separate Octave processes on the IDENTICAL input, for BOTH the v3.1.4-built
  binary (no sign normalisation) and the v3.5-built one (which has
  normalisation for the ``a<0`` case but not, apparently, enough to pin the
  exact ``a==c`` tie in every run). This is not a port defect to chase: no
  single real-MEX run is more authoritative than another to compare against,
  so every angle comparison below skips particles whose golden L and W are
  equal to within a tight relative tolerance (:data:`_CIRCULAR_REL_TOL`).
* **The minimum-area enclosing RECTANGLE is provably non-unique for a tied
  configuration** (already documented for the v3.1.4 port,
  ``test_cgal_mex_oracle.py::test_min_rectangle_area_matches_even_where_the_witness_could_differ``).
  This bank's own ``triangle`` builder (a hand-built staircase) was measured
  to hit exactly this tie: the real ``CGAL_RectSize.mex`` reports a 6x6
  axis-aligned square witness, this port's exact rotating-calipers algorithm
  reports an 8.07x4.54 rotated witness -- both AREA 25 diode^2, both equally
  minimal. :class:`TestAgainstTheOctaveGolden` therefore checks AREA
  agreement for every particle (a real area mismatch would be a genuine
  defect, since ``CGAL_RectSize`` is an exact, deterministic algorithm and
  area is the one witness-independent invariant) and additionally checks the
  exact ``(L, W, angle)`` triple only where the two algorithms happened to
  pick the SAME witness (measured: every particle except ``triangle``).

**Ellipse-angle tolerance, measured rather than assumed 1e-6** (the
discriminating test the P3D plan's uncertainty #1 asked for). Excluding the
circular-tie particles above, the maximum ``(have - want) mod pi`` observed
across every non-circular particle in every one of the five bank cases was
``5.249e-4`` rad, on the first ``blobs`` group particle (a random blob, well
away from any tie). The smallest was ``5.13e-6`` (``diag_band``). All of it
is explained by :func:`arrayprobe_uiops.min_ellipse`'s own documented
Khachiyan-vs-CGAL numerical gap (the same reason the axis LENGTHS carry a
1e-2 relative tolerance, not a tighter one) -- Khachiyan's stopping rule
converges the ANGLE much more slowly than the axis lengths for some point
configurations (verified directly: forcing ``max_iter`` from 3,000 to
100,000 on the pinned 6x9/3x7 case below shrinks the residual roughly
proportionally to ``1/max_iter``, i.e. it is a real but very slow-converging
numerical gap, not a wrong branch -- reaching 1e-6 this way would need on the
order of 10^5-10^6 iterations per ellipse call, which is not a viable
per-particle default). :data:`_ELLIPSE_ANGLE_TOL` is pinned at ``1e-3``,
comfortably above the measured maximum, and named here rather than loosened
silently. **No code in** :mod:`arrayprobe_uiops.min_ellipse` **was changed for
this** -- see that module's docstring point 5, unaffected, and this file's
own module-level note above on why no run of the real MEX is authoritative
enough to chase further for the circular case anyway.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from netCDF4 import Dataset
from tests._repo import needs_v314_engine

from arrayprobe_uiops.imgproc import PROBES_V35, imgproc_sm_v35, imgproc_variables_v35
from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG
from arrayprobe_uiops.min_ellipse import cgal_ellipse_size as cgal_ellipse_size_v35
from arrayprobe_uiops.min_rectangle import cgal_rect_size
from arrayprobe_uiops.rect_ellipse import RectEllipse, rect_ellipse_for_image
from arrayprobe_uiops.spec import read_binary_spec_v35

# ``test_v35_imgproc`` is a sibling test module, not a package -- make it
# importable regardless of how THIS module was invoked (bare
# ``test_v35_rect_ellipse`` via ``discover -s tests``, or the qualified
# ``tests.test_v35_rect_ellipse``, which does not put ``tests/`` on sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tests import _upstream  # noqa: E402
from tests._repo import repo_only  # noqa: E402

from test_v35_imgproc import _run_port_chain as _run_port_chain_old_fixture  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
V35_SRC = _upstream.source("uiops35")
DATA = Path(__file__).resolve().parent / "data"
GOLDEN_PATH = DATA / "v35_rect_ellipse_oracle.json"
RAW_FIXTURE = DATA / "v35_rect_ellipse_raw_fixture"
GOLDEN = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

DS = PROBES_V35["2DS"].ds  # 0.010 mm/diode, 2DS

_RECT_ELLIPSE_VARS = ("image_RectangleL", "image_RectangleW", "image_RectangleAngle",
                      "image_EllipseL", "image_EllipseW", "image_EllipseAngle")
_EXTENDED_VARS = ("image_EllipseX", "image_EllipseY")
_SEVEN_NEWHABIT_VARS = ("width_length_percentile", "circle_area_ratio",
                        "edge_maximum_dimension_ratio", "maximum_gap",
                        "opacity_coefficient", "aspect_ratio", "holroyd_perimeter")

#: See the module docstring's two "measured 2026-09-13" notes.
_CIRCULAR_REL_TOL = 1e-6
_ELLIPSE_ANGLE_TOL = 1e-3   # measured max 5.249e-4 rad (blobs[0], every non-circular case)
_RECT_ANGLE_TOL = 1e-6      # CGAL_RectSize is exact; no numerical residual expected
_GOLDEN_NON_COMPARABLE_ATTRS = ("Creation Time", "Image Source",
                                "arrayprobe_engine", "arrayprobe_profile")


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops35")


def _mod_diff(have: float, want: float, modulus: float) -> float:
    d = abs((have - want) % modulus)
    return min(d, modulus - d)


def _run_new_fixture_chain(tmp, *, i_new_habit, tas_ratio, i_rect_ellipse,
                           extended_ellipse_outputs, omit_rect_ellipse=False):
    """The whole PORT chain on THIS file's own non-degenerate fixture --
    :data:`RAW_FIXTURE` / :data:`GOLDEN`, built by
    ``octave_oracle/run_v35_rect_ellipse_bank.py``."""
    stem = Path(tmp) / "decoded"
    n_h, _n_v = read_binary_spec_v35(
        RAW_FIXTURE, stem, software="UIOOPS_v3.5",
        creation_time="2026/09/13 00:00:00", channels="H", sidecars=False,
    )
    assert n_h == GOLDEN["n_decoded_records"], (
        f"port decoded {n_h} H records, the golden's own bookkeeping recorded "
        f"{GOLDEN['n_decoded_records']}"
    )
    outfile = Path(tmp) / "out.proc.nc"
    kw = dict(
        iCalcAllDiodeStats=1, iNewHabit=i_new_habit, iQC=0,
        extended_ellipse_outputs=extended_ellipse_outputs,
        reject_config=STOCK_V35_REJECT_CONFIG,
        tas_time=GOLDEN["tas_time"], tas=GOLDEN["tas"], tas_ratio=tas_ratio,
        software="UIOOPS_v3.5", creation_time="2026/09/13 00:00:00",
    )
    if not omit_rect_ellipse:
        kw["iRectEllipse"] = i_rect_ellipse
    imgproc_sm_v35(str(stem) + ".H.nc", outfile, "2DS", 1, 1000, "ORACLES", **kw)
    with Dataset(outfile, "r") as ds:
        ds.set_auto_maskandscale(False)
        out = {
            "order": list(ds.variables),
            "attrs": {k: ds.getncattr(k) for k in ds.ncattrs()},
            "vars": {}, "var_attrs": {},
        }
        for name, v in ds.variables.items():
            out["vars"][name] = np.asarray(v[:])
            out["var_attrs"][name] = {k: v.getncattr(k) for k in v.ncattrs()}
    return out


def _make(rows, cols, r0, r1, c0, c1) -> np.ndarray:
    """A ``rows x cols`` all-``'1'`` ASCII image with ``[r0:r1, c0:c1]``
    (0-based, half-open) shadowed -- the same convention ``mex_build``'s own
    smoke test and this stage's Step 1 use."""
    t = np.full((rows, cols), ord("1"), dtype=np.uint8)
    t[r0:r1, c0:c1] = ord("0")
    return t


#: Step 1's smoke-test inputs, pinned. MATLAB is 1-based (``t(2:4,2:4)``);
#: the 0-based half-open equivalent is ``[1:4, 1:4]``.
_T5X5 = _make(5, 5, 1, 4, 1, 4)     # a 3x3 block -- circular (major == minor)
_T6X9 = _make(6, 9, 1, 4, 1, 8)     # a 3x7 block -- well-conditioned


class TestPinnedMexValues(unittest.TestCase):
    """Layer 2 by pinned numbers. Re-measure with, from the repository root::

        $oct = "$env:LOCALAPPDATA\\Programs\\GNU Octave\\Octave-11.3.0\\mingw64\\bin"
        & "$oct\\octave-cli.exe" --no-gui --quiet `
            --eval "addpath('scripts/validation/octave/mex_build'); \\
            t=repmat('1',5,5); t(2:4,2:4)='0'; \\
            [a,b,c,d,e]=CGAL_EllipseSize_v35(t); \\
                printf('V35 %.10g %.10g %.10g %.10g %.10g\\n',a,b,c,d,e); \\
            [a,b,c]=CGAL_EllipseSize(t); printf('V314 %.10g %.10g %.10g\\n',a,b,c); \\
            [p,q,r]=CGAL_RectSize(t); printf('RECT %.10g %.10g %.10g\\n',p,q,r); \\
            t2=repmat('1',6,9); t2(2:4,2:8)='0'; \\
            [a,b,c,d,e]=CGAL_EllipseSize_v35(t2); \\
                printf('V35b %.10g %.10g %.10g %.10g %.10g\\n',a,b,c,d,e); \\
            [a,b,c]=CGAL_EllipseSize(t2); printf('V314b %.10g %.10g %.10g\\n',a,b,c); \\
            [p,q,r]=CGAL_RectSize(t2); printf('RECTb %.10g %.10g %.10g\\n',p,q,r)"

    measured 2026-09-13: ``V35 2.828427125 2.828427125 0 3 3`` / ``V314
    3.828427125 3.828427125 1.5707963`` (or ``0`` -- see the class docstring
    below) / ``RECT 3 3 -0`` / ``V35b 8.485281374 2.828427125 0 5 3`` /
    ``V314b 9.485281374 3.828427125 1.5707963`` / ``RECTb 7 3 0``.

    The 5x5/3x3 case's ellipse is EXACTLY circular (major == minor to 9
    digits): its angle was separately measured (module docstring) to vary
    across fresh Octave processes for both real binaries, so it is not
    pinned here at all -- only L/W/X/Y, which are stable.
    """

    def test_rect_5x5(self):
        length, width, angle = cgal_rect_size(_T5X5)
        self.assertAlmostEqual(length, 3.0, places=9)
        self.assertAlmostEqual(width, 3.0, places=9)
        # non-unique witness (a square): any multiple of pi/2 is valid.
        self.assertLessEqual(_mod_diff(angle, 0.0, math.pi / 2), 1e-6)

    def test_rect_6x9(self):
        length, width, angle = cgal_rect_size(_T6X9)
        self.assertAlmostEqual(length, 7.0, places=9)
        self.assertAlmostEqual(width, 3.0, places=9)
        self.assertAlmostEqual(angle, 0.0, places=6)

    def test_ellipse_5x5_extended(self):
        re = rect_ellipse_for_image(_T5X5, extended=True)
        self.assertLess(abs(re.ell_l - 2.828427125), max(1e-6, 1e-2 * 2.828427125))
        self.assertLess(abs(re.ell_w - 2.828427125), max(1e-6, 1e-2 * 2.828427125))
        self.assertAlmostEqual(re.ell_y, 3.0, delta=1e-2)
        self.assertAlmostEqual(re.ell_x, 3.0, delta=1e-2)
        # angle deliberately not asserted -- circular tie, see class docstring.

    def test_ellipse_5x5_non_extended(self):
        re = rect_ellipse_for_image(_T5X5, extended=False)
        self.assertLess(abs(re.ell_l - 3.828427125), max(1e-6, 1e-2 * 3.828427125))
        self.assertLess(abs(re.ell_w - 3.828427125), max(1e-6, 1e-2 * 3.828427125))
        self.assertIsNone(re.ell_x)
        self.assertIsNone(re.ell_y)
        # angle deliberately not asserted -- circular tie, see class docstring.

    def test_ellipse_6x9_extended(self):
        """The discriminating case for uncertainty #1: well-conditioned
        (major >> minor), so angle IS meaningfully checkable -- and the
        answer is that the v3.5 PORT's angle agrees with the v3.5 MEX's
        (both near 0), to within the measured Khachiyan residual. See the
        module docstring for the numbers and why no code changed."""
        re = rect_ellipse_for_image(_T6X9, extended=True)
        self.assertLess(abs(re.ell_l - 8.485281374), max(1e-6, 1e-2 * 8.485281374))
        self.assertLess(abs(re.ell_w - 2.828427125), max(1e-6, 1e-2 * 2.828427125))
        self.assertLessEqual(_mod_diff(re.ell_angle, 0.0, math.pi), _ELLIPSE_ANGLE_TOL)
        self.assertAlmostEqual(re.ell_y, 5.0, delta=1e-2)   # :1297 Y<-output4 (diode direction)
        self.assertAlmostEqual(re.ell_x, 3.0, delta=1e-2)   # :1297 X<-output5 (time direction)

    def test_ellipse_6x9_non_extended(self):
        """L/W only. **Angle deliberately not asserted here** -- measured
        2026-09-13: the v3.1.4 PORT's angle (a plain eigendecomposition) does
        NOT reproduce the real v3.1.4 MEX's ``pi/2`` for this well-conditioned
        input, because that MEX value is itself an artifact of the missing
        ``a<0`` sign normalisation (module docstring) that this port's
        Khachiyan route has no equivalent internal state for. This is a
        pre-existing v3.1.4-port gap (``arrayprobe.geometry.min_ellipse``,
        off-limits to Part D) that Part D's new oracle exposes for the first
        time -- ``test_cgal_mex_oracle.py`` already never asserted this
        port's ellipse angle against a real MEX for the same underlying
        reason (ranked uncertainty #1: "neither port's ellipse angle has
        ever been asserted against a MEX")."""
        re = rect_ellipse_for_image(_T6X9, extended=False)
        self.assertLess(abs(re.ell_l - 9.485281374), max(1e-6, 1e-2 * 9.485281374))
        self.assertLess(abs(re.ell_w - 3.828427125), max(1e-6, 1e-2 * 3.828427125))

    def test_direct_mex_functions_agree_with_the_port_wrapper(self):
        """:func:`rect_ellipse_for_image` must not silently transform what
        the underlying geometry functions return."""
        major, minor, angle, out4, out5 = cgal_ellipse_size_v35(_T6X9)
        re = rect_ellipse_for_image(_T6X9, extended=True)
        self.assertEqual((re.ell_l, re.ell_w, re.ell_angle), (major, minor, angle))
        self.assertEqual(re.ell_y, out4)
        self.assertEqual(re.ell_x, out5)

    @needs_v314_engine
    def test_direct_mex_functions_agree_with_the_port_wrapper_v314(self):
        from arrayprobe.geometry.min_ellipse import cgal_ellipse_size as cgal_ellipse_size_v314

        major3, minor3, angle3 = cgal_ellipse_size_v314(_T6X9)
        re3 = rect_ellipse_for_image(_T6X9, extended=False)
        self.assertEqual((re3.ell_l, re3.ell_w, re3.ell_angle), (major3, minor3, angle3))


class TestTheGoldenIsWhatItClaims(unittest.TestCase):
    def test_fixture_sha_matches(self):
        self.assertEqual(GOLDEN["raw_fixture_sha256"],
                         hashlib.sha256(RAW_FIXTURE.read_bytes()).hexdigest())

    @repo_only
    def test_vendored_hashes_match(self):
        pairs = {
            "imgproc_sm_sha256": "imgProc_sm.m",
            "read_binary_spec_sha256": "read_binary_SPEC.m",
            "cgal_rectsize_sha256": "CGAL_RectSize.cpp",
            "cgal_ellipsesize_v35_sha256": "CGAL_EllipseSize.cpp",
        }
        for key, relname in pairs.items():
            with self.subTest(key=key):
                self.assertEqual(GOLDEN[key],
                                 hashlib.sha256((V35_SRC / relname).read_bytes()).hexdigest())

    def test_five_cases_present(self):
        self.assertEqual(set(GOLDEN["cases"]),
                         {"re0_nh0", "re1_ext0_nh0", "re1_ext1_nh0",
                          "re1_ext1_nh0_tasratio", "re1_ext1_nh1"})

    def test_schema_sets_per_case(self):
        want = {
            "re0_nh0": (),
            "re1_ext0_nh0": _RECT_ELLIPSE_VARS,
            "re1_ext1_nh0": _RECT_ELLIPSE_VARS + _EXTENDED_VARS,
            "re1_ext1_nh0_tasratio": _RECT_ELLIPSE_VARS + _EXTENDED_VARS,
            "re1_ext1_nh1": _RECT_ELLIPSE_VARS + _EXTENDED_VARS + _SEVEN_NEWHABIT_VARS,
        }
        rect_ellipse_ish = set(_RECT_ELLIPSE_VARS) | set(_EXTENDED_VARS) | set(_SEVEN_NEWHABIT_VARS)
        for case_name, extra in want.items():
            with self.subTest(case=case_name):
                have = set(GOLDEN["cases"][case_name]["variables"])
                self.assertTrue(set(extra) <= have)
                self.assertEqual(have & rect_ellipse_ish, set(extra))

    def test_stdout_markers_recorded(self):
        want = {
            "re0_nh0": (False, False),
            "re1_ext0_nh0": (False, True),
            "re1_ext1_nh0": (True, False),
            "re1_ext1_nh0_tasratio": (True, False),
            "re1_ext1_nh1": (True, False),
        }
        for case_name, (using, not_using) in want.items():
            with self.subTest(case=case_name):
                case = GOLDEN["cases"][case_name]
                self.assertEqual(case["stdout_has_using_revised"], using)
                self.assertEqual(case["stdout_has_not_using_revised"], not_using)

    def test_ext0_ellipse_l_equals_ext1_plus_one_diode(self):
        """The v3.1.4 "+1" major/minor bias (1b), re-checked from the GOLDEN
        (the bank asserted this on the live Octave run; this re-checks the
        saved JSON -- two separate places)."""
        ds = GOLDEN["diode_size"]
        a = np.asarray(GOLDEN["cases"]["re1_ext0_nh0"]["variables"]["image_EllipseL"]["values"])
        b = np.asarray(GOLDEN["cases"]["re1_ext1_nh0"]["variables"]["image_EllipseL"]["values"])
        np.testing.assert_allclose((a - b) / ds, 1.0, atol=1e-6)

    def test_ellipse_x_before_y_in_the_variable_order(self):
        order = GOLDEN["cases"]["re1_ext1_nh0"]["order"]
        self.assertLess(order.index("image_EllipseX"), order.index("image_EllipseY"))


class TestAgainstTheOctaveGolden(unittest.TestCase):
    """The port's own chain against the real, unmodified vendored v3.5 chain
    (both real ``CGAL_EllipseSize`` binaries). Every variable, order, and
    attribute; values with the tolerances the module docstring measures and
    names."""

    _CASES = {
        "re0_nh0": dict(i_new_habit=0, tas_ratio=None,
                       i_rect_ellipse=0, extended_ellipse_outputs=None),
        "re1_ext0_nh0": dict(i_new_habit=0, tas_ratio=None,
                            i_rect_ellipse=1, extended_ellipse_outputs=False),
        "re1_ext1_nh0": dict(i_new_habit=0, tas_ratio=None,
                            i_rect_ellipse=1, extended_ellipse_outputs=True),
        "re1_ext1_nh0_tasratio": dict(
            i_new_habit=0, tas_ratio=[0.7] * GOLDEN["n_decoded_records"],
            i_rect_ellipse=1, extended_ellipse_outputs=True),
        "re1_ext1_nh1": dict(i_new_habit=1, tas_ratio=None,
                            i_rect_ellipse=1, extended_ellipse_outputs=True),
    }

    def _check_rect_pair_and_angle(self, case_name, golden, got):
        have_l = np.asarray(got["vars"]["image_RectangleL"], dtype=float)
        have_w = np.asarray(got["vars"]["image_RectangleW"], dtype=float)
        have_a = np.asarray(got["vars"]["image_RectangleAngle"], dtype=float)
        want_l = np.asarray(golden["variables"]["image_RectangleL"]["values"], dtype=float)
        want_w = np.asarray(golden["variables"]["image_RectangleW"]["values"], dtype=float)
        want_a = np.asarray(golden["variables"]["image_RectangleAngle"]["values"], dtype=float)

        have_area = (have_l / DS - 1.0) * (have_w / DS - 1.0)
        want_area = (want_l / DS - 1.0) * (want_w / DS - 1.0)
        np.testing.assert_allclose(
            have_area, want_area, rtol=1e-6, atol=1e-9,
            err_msg=f"{case_name}: image_RectangleL/W AREA mismatch -- CGAL_RectSize is exact, "
                    "so a real area mismatch is a defect, not a witness tie")

        witness_matches = (np.isclose(have_l, want_l, rtol=1e-9, atol=1e-9)
                          & np.isclose(have_w, want_w, rtol=1e-9, atol=1e-9))
        n_mismatch = int((~witness_matches).sum())
        self.assertLessEqual(
            n_mismatch, 1,
            f"{case_name}: {n_mismatch} particles picked a rectangle witness different from "
            "the golden's -- more than the one known tie (module docstring's \"triangle\")")

        for i in np.nonzero(witness_matches)[0]:
            l_, w_ = want_l[i], want_w[i]
            modulus = (math.pi / 2) if abs(l_ - w_) < max(1e-9, _CIRCULAR_REL_TOL * max(l_, w_)) \
                else math.pi
            d = _mod_diff(float(have_a[i]), float(want_a[i]), modulus)
            self.assertLessEqual(
                d, _RECT_ANGLE_TOL,
                f"{case_name}: image_RectangleAngle[{i}] = {have_a[i]}, want {want_a[i]} "
                f"mod {modulus}")

    def _check_ellipse_angle(self, case_name, golden, got, *, extended):
        have_a = np.asarray(got["vars"]["image_EllipseAngle"], dtype=float)
        if not extended:
            # Non-extended (``extended_ellipse_outputs=False``) calls
            # arrayprobe.geometry.min_ellipse.cgal_ellipse_size (v3.1.4 port,
            # off-limits to Part D). Measured 2026-09-13
            # (TestPinnedMexValues.test_ellipse_6x9_non_extended's docstring):
            # that port's angle does not reproduce the real v3.1.4 MEX's
            # value even on a well-conditioned particle, because the MEX
            # value is itself an artifact of a missing sign-normalisation
            # this port's Khachiyan route has no equivalent for -- a
            # pre-existing v3.1.4-port gap, not something Part D changes.
            # Only sanity-checked here: finite, in the documented range.
            self.assertTrue(np.all(np.isfinite(have_a)), f"{case_name}: non-finite angle")
            self.assertTrue(np.all(np.abs(have_a) <= math.pi / 2 + 1e-6),
                            f"{case_name}: angle outside (-pi/2, pi/2]")
            return
        want_a = np.asarray(golden["variables"]["image_EllipseAngle"]["values"], dtype=float)
        want_l = np.asarray(golden["variables"]["image_EllipseL"]["values"], dtype=float)
        want_w = np.asarray(golden["variables"]["image_EllipseW"]["values"], dtype=float)
        for i in range(len(have_a)):
            circular_tol = max(1e-9, _CIRCULAR_REL_TOL * max(want_l[i], want_w[i]))
            if abs(want_l[i] - want_w[i]) < circular_tol:
                continue  # circular by construction -- see module docstring
            d = _mod_diff(float(have_a[i]), float(want_a[i]), math.pi)
            self.assertLessEqual(
                d, _ELLIPSE_ANGLE_TOL,
                f"{case_name}: image_EllipseAngle[{i}] = {have_a[i]}, want {want_a[i]}")

    def _check_case(self, case_name):
        kw = self._CASES[case_name]
        with tempfile.TemporaryDirectory() as tmp:
            got = _run_new_fixture_chain(tmp, **kw)
        golden = GOLDEN["cases"][case_name]

        self.assertEqual(got["order"], golden["order"],
                         "the port's variable order must equal the golden's")

        spec_table = {s.name: s.xtype for s in imgproc_variables_v35(
            iRectEllipse=kw["i_rect_ellipse"], iCalcAllDiodeStats=1, iQC=0,
            iNewHabit=kw["i_new_habit"], extended_ellipse_outputs=kw["extended_ellipse_outputs"],
            probetype=2)}
        self.assertEqual(set(got["vars"]), set(golden["variables"]))

        handled_together = {"image_RectangleL", "image_RectangleW", "image_RectangleAngle",
                            "image_EllipseAngle"}
        if "image_RectangleL" in golden["variables"]:
            self._check_rect_pair_and_angle(case_name, golden, got)
        if "image_EllipseAngle" in golden["variables"]:
            self._check_ellipse_angle(case_name, golden, got,
                                      extended=bool(kw["extended_ellipse_outputs"]))

        for name in golden["variables"]:
            with self.subTest(variable=name):
                want_raw = golden["variables"][name]["values"]
                have = got["vars"][name]
                if name not in handled_together:
                    if name in ("image_EllipseL", "image_EllipseW") + _EXTENDED_VARS:
                        want = np.asarray(want_raw, dtype=float)
                        np.testing.assert_allclose(have.astype(float), want,
                                                   rtol=1e-2, atol=1e-6)
                    elif spec_table[name] == "double":
                        want = np.asarray(want_raw, dtype=float)
                        np.testing.assert_allclose(have.astype(float), want, rtol=1e-9,
                                                   equal_nan=True)
                    else:
                        np.testing.assert_array_equal(have, np.asarray(want_raw))
                self.assertEqual(dict(got["var_attrs"][name]),
                                 golden["variables"][name]["attrs"])

        for key, value in golden["global_attributes"].items():
            if key in _GOLDEN_NON_COMPARABLE_ATTRS:
                continue
            with self.subTest(attribute=key):
                self.assertEqual(str(got["attrs"][key]), value)

    def test_re0_nh0(self):
        self._check_case("re0_nh0")

    def test_re1_ext0_nh0(self):
        self._check_case("re1_ext0_nh0")

    def test_re1_ext1_nh0(self):
        self._check_case("re1_ext1_nh0")

    def test_re1_ext1_nh0_tasratio(self):
        self._check_case("re1_ext1_nh0_tasratio")

    def test_re1_ext1_nh1(self):
        self._check_case("re1_ext1_nh1")


class TestDegenerateImagesDoNotAbortThePort(unittest.TestCase):
    """A16, layer 3 stated: MATLAB aborts the interpreter on a collinear
    image under ``CGAL_EllipseSize`` (``test_cgal_mex_oracle.py:113-134``),
    uncatchable from ``.m`` code. This bank's OWN fixture is deliberately
    non-degenerate (module docstring) and cannot exercise this, so this test
    runs the port on the EXISTING 27-particle ``imgProc_sm.m`` driver fixture instead -- which
    contains ``pixel1`` (1 shadowed pixel) and ``two_pixel_diagonal`` (2),
    both of which the real MEX cannot process at all.

    Bug found and fixed here (2026-09-13, Part D, not the Step-7 angle
    question): :func:`arrayprobe_uiops.min_ellipse._min_area_ellipse_with_center`
    used to ``return None`` for fewer than 3 points -- before ever reaching
    its own ``len(unique) < 3`` degenerate-segment branch a few lines below,
    which already existed to handle exactly this -- so :func:`extended=True`
    on ``pixel1``/``two_pixel_diagonal`` raised ``TypeError: cannot unpack
    non-iterable NoneType object`` instead of returning a finite degenerate
    answer. Latent until Part D because no earlier caller reached
    ``extended=True`` on a real per-particle loop.
    """

    def _run(self, extended):
        with tempfile.TemporaryDirectory() as tmp:
            return _run_port_chain_old_fixture(
                tmp, i_new_habit=0, tas_ratio=None,
                i_rect_ellipse=1, extended_ellipse_outputs=extended)

    def test_extended_false_completes(self):
        got = self._run(False)
        length = got["vars"]["image_EllipseL"].astype(float)
        self.assertEqual(len(length), 27)
        self.assertTrue(np.all(np.isfinite(length) | np.isnan(length)))

    def test_extended_true_completes(self):
        got = self._run(True)
        length = got["vars"]["image_EllipseL"].astype(float)
        self.assertEqual(len(length), 27)
        self.assertTrue(np.all(np.isfinite(length) | np.isnan(length)))
        # RectEllipse dataclass fields carried through for the extended path.
        self.assertIn("image_EllipseX", got["vars"])
        self.assertIn("image_EllipseY", got["vars"])


class TestDefaultIsByteIdentical(unittest.TestCase):
    """``iRectEllipse`` omitted (defaults to 0, ``imgproc.py``'s own
    signature default) must write exactly what an explicit ``iRectEllipse=0``
    call writes -- the ``TestIQCDefaultIsZero`` pattern."""

    def test_default_matches_explicit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            default = _run_new_fixture_chain(
                tmp, i_new_habit=0, tas_ratio=None, i_rect_ellipse=0,
                extended_ellipse_outputs=None, omit_rect_ellipse=True)
        with tempfile.TemporaryDirectory() as tmp:
            explicit = _run_new_fixture_chain(
                tmp, i_new_habit=0, tas_ratio=None, i_rect_ellipse=0,
                extended_ellipse_outputs=None)
        self.assertEqual(default["order"], explicit["order"])
        for name in default["vars"]:
            with self.subTest(variable=name):
                np.testing.assert_array_equal(default["vars"][name], explicit["vars"][name])


class TestRectEllipseDataclass(unittest.TestCase):
    """The port module's own small surface, independent of the whole chain."""

    def test_non_extended_has_no_centre(self):
        re = rect_ellipse_for_image(_T6X9, extended=False)
        self.assertIsInstance(re, RectEllipse)
        self.assertIsNone(re.ell_x)
        self.assertIsNone(re.ell_y)

    def test_extended_has_a_centre(self):
        re = rect_ellipse_for_image(_T6X9, extended=True)
        self.assertIsNotNone(re.ell_x)
        self.assertIsNotNone(re.ell_y)


if __name__ == "__main__":
    unittest.main()
