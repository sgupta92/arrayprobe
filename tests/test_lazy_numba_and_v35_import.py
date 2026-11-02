# SPDX-License-Identifier: BSD-3-Clause
"""Since 2026-09-15, ``import arrayprobe`` must not pay for numba or arrayprobe_uiops.

**The measurement that motivated this.** ``python -X importtime -c "import arrayprobe.cli"``
cumulative 4.74 s, of which numba alone was 2.24 s, reached through
``arrayprobe.config -> arrayprobe.profiles -> arrayprobe_uiops.measure -> arrayprobe.reject ->
numba``; ``import arrayprobe`` alone 2.75 s wall (the archived R6
software review, section 9). So a plain ``arrayprobe --help`` or notebook
cell paid for JIT infrastructure and a whole second engine it might never touch, and the
*v3.1.4* package imported the *v3.5* package at import time through ``profiles``.

**The fix, in two places.**

* ``arrayprobe.reject`` no longer imports numba at module load. ``HAVE_NUMBA`` is now a
  lazy module attribute (PEP 562 ``__getattr__``) that imports numba and JIT-decorates the
  five kernels exactly once, on first access -- whether that access is direct
  (``reject.HAVE_NUMBA``) or through the first call to ``scan_slice``/
  ``is_it_hollow_sidescan``.
* ``arrayprobe.profiles`` no longer imports ``arrayprobe_uiops.measure`` at module load.
  ``STOCK_V35`` is built once, on first actual need, whether that is the module attribute,
  ``PROFILES["stock-v3.5"]``, ``profile("stock-v3.5")``, or iterating ``PROFILES`` down to
  values; ``SHIPPED`` and plain iteration of ``PROFILES`` still see the name
  ``"stock-v3.5"`` without building it, since a name costs nothing and the import is what
  was worth deferring.

Neither change moves a computed byte: the JIT kernels and ``STOCK_V35``'s field values are
unchanged, only *when* the two imports happen. ``tests/test_reject_numba_equivalence.py``,
``tests/test_stock_v35_profile.py`` and the tracked v3.5 demo-reference comparison in
``tests/test_demo_reference.py`` (``TestCheckV35ReportsNoProblems`` and friends) are the
byte-identity evidence for that; this file only checks *when* the two packages enter
``sys.modules``.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

from tests._repo import needs_file, needs_source, needs_v314_engine  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "src"
REJECT_PY = SRC / "arrayprobe" / "reject.py"
PROFILES_PY = SRC / "arrayprobe" / "profiles.py"


#: The ``arrayprobe_uiops`` modules the v3.1.4 package may load at import time: the package
#: itself and the standard-library-only ``provenance`` parser, which lives in the v3.5 engine
#: because code both engines share lives there, and the NumPy-only ``diode_mask`` (the
#: stuck-diode rule and re-illumination both engines apply).
#: Every other
#: ``arrayprobe_uiops`` module is the engine, whose import is what the deferral exists to
#: avoid; adding a module here is a decision, not a fix. ``particle`` (NumPy-only
#: ``shadow_mask``) joined as an approved import-time leaf. ``ncio`` (the MATLAB ``netcdf.*``
#: layer both engines write through) joined 2026-10-03, author-approved although it imports
#: netCDF4; ``arrayprobe.ncio`` is an alias of it.
V35_SHARED = frozenset({"arrayprobe_uiops", "arrayprobe_uiops.provenance",
                        "arrayprobe_uiops.diode_mask", "arrayprobe_uiops.particle",
                        "arrayprobe_uiops.ncio",
                        # v3.1.4 split (slices 9b-10a): the shared leaf modules the port
                        # imports at load time, none of them the engine (measure, imgproc,
                        # sizedist, reject, ...) whose deferral this file guards.
                        "arrayprobe_uiops.combine_fork", "arrayprobe_uiops.constants",
                        "arrayprobe_uiops.geometry_core", "arrayprobe_uiops.habit_core",
                        "arrayprobe_uiops.imgproc_core", "arrayprobe_uiops.matlab_compat",
                        "arrayprobe_uiops.particle_perimeter", "arrayprobe_uiops.profiles",
                        "arrayprobe_uiops.readers", "arrayprobe_uiops.readers.pms",
                        "arrayprobe_uiops.readers.tasinfo", "arrayprobe_uiops.reject_core",
                        "arrayprobe_uiops.sample_area", "arrayprobe_uiops.sizedist_core",
                        "arrayprobe_uiops.spec_core",
                        # 2026-10-10: the standard-library-only error both engines and
                        # the uiops selector raise when the v3.1.4 engine is absent.
                        "arrayprobe_uiops.engine_absence"})

#: The module the deferred ``STOCK_V35`` build imports (``arrayprobe/profiles.py``), so its
#: presence in ``sys.modules`` is the proof that the build ran.
V35_BUILD = "arrayprobe_uiops.measure"


def _assert_no_v35_engine(what: str) -> str:
    """A script line asserting that ``what`` loaded no v3.5 engine module beyond
    :data:`V35_SHARED`."""
    return (
        "_v35 = sorted(m for m in sys.modules if m.split('.')[0] == 'arrayprobe_uiops' "
        f"and m not in {sorted(V35_SHARED)!r})\n"
        f"assert not _v35, ('the v3.5 engine was imported by {what}', _v35)\n"
    )


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=120,
        cwd=str(Path(__file__).resolve().parent.parent),
    )


class ImportArrayprobeLoadsNeitherEagerly(unittest.TestCase):
    """The core claim: importing the port leaves numba and arrayprobe_uiops untouched."""

    def test_import_arrayprobe_does_not_load_numba_or_v35(self):
        result = _run(
            "import sys\n"
            "import arrayprobe\n"
            "assert 'numba' not in sys.modules, 'numba was imported by `import arrayprobe`'\n"
            + _assert_no_v35_engine("`import arrayprobe`")
            + "print('ok')\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

    def test_import_arrayprobe_cli_does_not_load_numba_or_v35(self):
        result = _run(
            "import sys\n"
            "import arrayprobe.cli\n"
            "assert 'numba' not in sys.modules, 'numba was imported by `import arrayprobe.cli`'\n"
            + _assert_no_v35_engine("`import arrayprobe.cli`")
            + "print('ok')\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

    def test_import_arrayprobe_profiles_alone_does_not_load_v35(self):
        """The narrowest possible repro of the slow-import chain: importing the module that
        used to do ``from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG`` at
        its own top level."""
        result = _run(
            "import sys\n"
            "import arrayprobe.profiles\n"
            + _assert_no_v35_engine("`import arrayprobe.profiles`")
            + "print('ok')\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

    @needs_v314_engine
    def test_import_arrayprobe_reject_alone_does_not_load_numba(self):
        result = _run(
            "import sys\n"
            "import arrayprobe.reject\n"
            "assert 'numba' not in sys.modules\n"
            "print('ok')\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)


class FirstUseStillLoadsThem(unittest.TestCase):
    """Prove the deferral is real deferral, not accidental breakage: each package
    is still reachable, and still lands in sys.modules, the first time it is
    actually needed."""

    def test_stock_v35_attribute_access_loads_v35_not_numba(self):
        result = _run(
            "import sys\n"
            "from arrayprobe.profiles import STOCK_V35\n"
            f"assert {V35_BUILD!r} in sys.modules, 'STOCK_V35 access did not build it'\n"
            "assert 'numba' not in sys.modules, "
            "'STOCK_V35 access should not by itself need numba'\n"
            "assert STOCK_V35.name == 'stock-v3.5'\n"
            "print('ok')\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

    def test_profiles_by_name_lookup_loads_v35(self):
        result = _run(
            "import sys\n"
            "from arrayprobe.profiles import profile\n"
            "p = profile('stock-v3.5')\n"
            f"assert {V35_BUILD!r} in sys.modules\n"
            "assert p.name == 'stock-v3.5'\n"
            "print('ok')\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

    def test_profiles_mapping_subscript_loads_v35(self):
        result = _run(
            "import sys\n"
            "from arrayprobe.profiles import PROFILES\n"
            + _assert_no_v35_engine("constructing PROFILES")
            + "p = PROFILES['stock-v3.5']\n"
            f"assert {V35_BUILD!r} in sys.modules\n"
            "assert p.name == 'stock-v3.5'\n"
            "print('ok')\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

    def test_shipped_and_iteration_do_not_force_the_v35_build(self):
        """A name is free; only the object behind ``stock-v3.5`` costs an import.
        Listing names (SHIPPED, or iterating PROFILES) must not pay for it."""
        result = _run(
            "import sys\n"
            "from arrayprobe.profiles import PROFILES, SHIPPED\n"
            "assert 'stock-v3.5' in SHIPPED\n"
            "assert 'stock-v3.5' in set(PROFILES)\n"
            + _assert_no_v35_engine("naming stock-v3.5")
            + "print('ok')\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

    @needs_v314_engine
    def test_have_numba_attribute_access_loads_numba(self):
        result = _run(
            "import sys\n"
            "from arrayprobe import reject\n"
            "assert 'numba' not in sys.modules\n"
            "have = reject.HAVE_NUMBA\n"
            "assert have is True or have is False\n"
            "assert ('numba' in sys.modules) == have, "
            "'HAVE_NUMBA access should import numba iff numba is installed'\n"
            "print('ok', have)\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

    @needs_v314_engine
    def test_scan_slice_call_loads_numba_and_dispatches_correctly(self):
        """First call, not just first attribute access, must also trigger the
        load -- and the dispatch has to still agree with the pure-Python body,
        or the laziness bought speed at the cost of the fidelity guarantee."""
        result = _run(
            "import sys\n"
            "from arrayprobe import reject\n"
            "import numpy as np\n"
            "row = np.array([False, True, False, True, True], dtype=bool)\n"
            "got = reject.scan_slice(row)\n"
            "want = reject._scan_slice_reference(row)\n"
            "assert (got.min_pos_lite, got.max_pos_lite, got.n_lite) == want, (got, want)\n"
            "assert ('numba' in sys.modules) == reject.HAVE_NUMBA\n"
            "print('ok')\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)


class RegistrationStillRefusesTheShippedV35Name(unittest.TestCase):
    """register_profile's duplicate-name guard used to read _REGISTRY, which
    now legitimately lacks "stock-v3.5" until first use -- it must still
    refuse the name, checked against SHIPPED as well, in that window."""

    @needs_v314_engine
    def test_registering_stock_v35_is_refused_before_first_use(self):
        result = _run(
            "import sys\n"
            "from arrayprobe.profiles import FidelityProfile, register_profile, "
            "DEFAULT_REJECT_CONFIG\n"
            "from arrayprobe.reject import DEFAULT_REJECT_CONFIG as RC\n"
            + _assert_no_v35_engine("importing profiles")
            + "dupe = FidelityProfile(name='stock-v3.5', description='dupe', "
            "spec_buffer_guard=True, hvps_reader='spec', "
            "diode_stats_counts_shadowed=True, zero_image_particle_recovery=True, "
            "time_in_seconds_from_tas=True, inter_arrival_in_seconds=True, "
            "shadow_diode_reillumination=False, imgproc_output_typing='typed', "
            "nan_tas_substitution=True, "
            "reject_thresholds=RC)\n"
            "try:\n"
            "    register_profile(dupe)\n"
            "except ValueError as exc:\n"
            "    assert 'stock-v3.5' in str(exc)\n"
            "    print('ok')\n"
            "else:\n"
            "    raise SystemExit('register_profile accepted a shipped name')\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)


@needs_source
class StaticGuardAgainstTheEagerImportReturning(unittest.TestCase):
    """A regression that re-adds either eager top-level import would slip past
    a reviewer who only skims the diff, since both modules still import numba
    and arrayprobe_uiops -- just later. Check the AST directly: no top-level
    ``import`` or ``from ... import`` naming ``numba``/``arrayprobe_uiops`` may
    appear outside a function or class body. This is the check that "a
    mutation re-adding the eager import" trips: reverting either fix (moving
    the numba import back to reject.py's top level, or the arrayprobe_uiops
    import back to profiles.py's top level) makes this fail, independently of
    the subprocess tests above.
    """

    @staticmethod
    def _toplevel_import_names(path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names: set[str] = set()
        for node in tree.body:  # module top level only -- not nested in def/try/if
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        return names

    @needs_file("src/arrayprobe/reject.py")
    def test_reject_py_names_no_top_level_numba_import(self):
        names = self._toplevel_import_names(REJECT_PY)
        self.assertNotIn(
            "numba", names,
            "arrayprobe/reject.py imports numba at module level again -- this is exactly "
            "the slow-import regression (numba loaded at import time): "
            "move it into _ensure_numba_loaded().")

    def test_profiles_py_names_no_top_level_v35_import(self):
        # Split slice 10a(i): the profile type and registry live in the light leaf
        # arrayprobe_uiops.profiles (it imports only reject_core); any other
        # top-level arrayprobe_uiops import is still the slow-import regression.
        # reject_core is the second light leaf (numpy + dataclasses only; the reject
        # thresholds profiles.py needs live there so the v3.1.4 engine can be absent).
        LIGHT_LEAVES = {"arrayprobe_uiops.profiles", "arrayprobe_uiops.reject_core"}
        tree = ast.parse(PROFILES_PY.read_text(encoding="utf-8"), filename=str(PROFILES_PY))
        names = {"arrayprobe_uiops" for node in tree.body
                 if isinstance(node, ast.ImportFrom) and node.module
                 and node.module.split(".")[0] == "arrayprobe_uiops"
                 and node.module not in LIGHT_LEAVES}
        names |= {"arrayprobe_uiops" for node in tree.body if isinstance(node, ast.Import)
                  for a in node.names if a.name.split(".")[0] == "arrayprobe_uiops"}
        self.assertNotIn(
            "arrayprobe_uiops", names,
            "arrayprobe/profiles.py imports arrayprobe_uiops at module level again -- this "
            "is exactly the slow-import regression (numba loaded at import time): "
            "move it into _build_stock_v35().")

    def test_the_ast_walk_actually_flags_a_top_level_import(self):
        """Executed, not read: prove the checker above would catch the mutation
        it claims to, on a synthetic module shaped like the reverted code."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            mutated = Path(td) / "mutated_reject.py"
            mutated.write_text(
                "from numba import njit\n\n\ndef f():\n    return njit\n",
                encoding="utf-8",
            )
            names = self._toplevel_import_names(mutated)
            self.assertIn("numba", names)


if __name__ == "__main__":
    unittest.main()
