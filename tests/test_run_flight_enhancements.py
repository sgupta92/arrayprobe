# SPDX-License-Identifier: BSD-3-Clause
"""``run_flight.py --enhancements`` -- the driver path that runs a UIOOPS engine WITH the
enhancements the config file names (2026-09-20).

**What was wrong until today.** No driver path ran a UIOOPS engine with enhancements at all.
``scripts/run_flight.py``'s confirmation panel printed ``enhancements  OFF -- always``, and
``_apply_config`` read the config's ``[enhancements]`` table, logged the requested names, and
declined to honour them (``-- this driver runs the port only; apply them from the enhancements
package``). The only path that applied anything was the separate ``arrayprobe-enhanced run``
console script, which runs the port again in a subprocess of its own. So "v3.5 with all
enhancements" -- what every non-ORACLES number is supposed to come from -- was not producible by
any command that existed, and nothing written to disk said which arm a number came from.

**The three properties pinned here**, in the order they matter:

1. the flag OFF leaves the port's own products byte-identical -- asserted on the written bytes
   and with ``np.array_equal``, never a tolerance, and asserted for the ON arm too, because an
   applier that overwrote the faithful file would be a fidelity defect, not a feature;
2. the flag ON actually **applies** the correction -- asserted by a value that moved in the file
   the run wrote, not by a log line. This is the test that fails without the change;
3. the port still imports nothing from ``arrayprobe_enhancements``
   (``tests/test_no_enhancement_coupling.py`` stays green; this file adds the driver-side half:
   the import inside ``scripts/`` is ``ImportError``-guarded, so an uninstalled package is a named
   refusal and never a traceback).

The synthetic proc/sd pair below stands in for a flight: these appliers read and rewrite netCDF
columns, so what they need is a stamped file of the right shape, not hours of decode. The stamp
is the real thing -- ``run_flight``'s own ``write_stamp`` -- because ``locate_outputs`` refuses
an unstamped output, and that refusal is part of what is being exercised.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import netCDF4
import numpy as np
from tests._driver import driver_source

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
_spec = importlib.util.spec_from_file_location("run_flight", ROOT / "scripts" / "run_flight.py")
assert _spec is not None and _spec.loader is not None
run_flight = importlib.util.module_from_spec(_spec)
sys.modules.setdefault(_spec.name, run_flight)
_spec.loader.exec_module(run_flight)

try:
    import arrayprobe_enhancements.pipeline  # noqa: F401
    _HAVE_ENHANCEMENTS = True
except ImportError:                                   # pragma: no cover -- CI installs it
    _HAVE_ENHANCEMENTS = False

#: What the synthetic proc file carries. Deliberately NOT sorted and not equal to each other:
#: the correction is a swap, so identical columns would pass whether it ran or not.
MAX_HOLE = np.array([3.0, 11.0, 2.0, 7.0], dtype="f8")
EDGE = np.array([19.0, 23.0, 29.0, 31.0], dtype="f8")


class _Args:
    """The subset of ``main``'s argparse namespace the enhancement path reads."""

    def __init__(self, out, config, *, enhancements=False):
        self.out = out
        self.config = config
        self.enhancements = enhancements
        self.diode_corrected = False
        self.accept_unstamped = False
        self.iat_file = run_flight.IAT_FILE


def _write_proc(path: Path) -> None:
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", len(MAX_HOLE))
        ds.createVariable("max_hole_diameter", "f8", ("time",))[:] = MAX_HOLE
        ds.createVariable("edge_at_max_hole", "f8", ("time",))[:] = EDGE
        # Present so particle_number_all_fix's audit has something to read if a future
        # config names it; unused by hole_edge_swap.
        ds.createVariable("image_length", "f8", ("time",))[:] = np.arange(len(MAX_HOLE))


def _write_sd(path: Path) -> None:
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", 2)
        ds.createVariable("conc_minR", "f8", ("time",))[:] = np.array([1.0, 2.0])


def _digest(out_dir: Path) -> dict[str, bytes]:
    """Every file in ``out_dir``, by name, as bytes. The byte-identity comparison."""
    return {p.name: p.read_bytes() for p in sorted(out_dir.iterdir()) if p.is_file()}


class _Fixture(unittest.TestCase):
    """A stamped proc/sd pair in a temp directory, plus a config naming one enhancement."""

    STEM = "base160906064017"
    ENHANCEMENTS = "hole_edge_swap = true\n"

    def setUp(self):
        self.out = Path(tempfile.mkdtemp()) / "_decoded"
        self.out.mkdir(parents=True)
        self.proc = run_flight.proc_path(self.STEM, self.out)
        self.sd = run_flight.sd_path(self.STEM, self.out)
        _write_proc(self.proc)
        _write_sd(self.sd)
        # The real stamps, from the driver's own labellers -- locate_outputs refuses an
        # unstamped output, and a hand-written stamp would not be the thing under test.
        run_flight.write_stamp(self.proc, run_flight.proc_call_label())
        run_flight.write_stamp(self.sd, run_flight.sd_call_label(run_flight.IAT_FILE))
        self.config = self.out.parent / "run.toml"
        self.config.write_text(
            '[fidelity]\nprofile = "ORACLES_PRODUCTION"\n'
            "[enhancements]\n" + self.ENHANCEMENTS, encoding="utf-8")

    def _apply(self, *, enhancements: bool) -> tuple[int, str]:
        """The exact call ``main`` makes at its hook site, under the same gate."""
        args = _Args(self.out, self.config, enhancements=enhancements)
        buf = io.StringIO()
        rc = 0
        with redirect_stdout(buf):
            if getattr(args, "enhancements", False):
                rc = run_flight.apply_enhancements_to_run(args, [self.STEM])
        return rc, buf.getvalue()


class TheFlagOffChangesNothing(_Fixture):
    """Property 1. Installing the enhancements package, or naming modules in a config, must not
    move one byte of what the port writes -- that is what "opt-in, default-off" means, and it is
    the reason the enhancements live outside the port at all. This fixture is a 2D-S flight, on
    the lineage where no correction runs by default; off it, see test_protective_default.py."""

    def test_off_leaves_the_directory_byte_identical(self):
        before = _digest(self.out)
        rc, log = self._apply(enhancements=False)
        self.assertEqual(rc, 0)
        self.assertEqual(_digest(self.out), before,
                         "a run without --enhancements wrote, removed or changed a file")
        self.assertEqual(log, "", "a run without --enhancements said something about them")

    def test_off_leaves_the_proc_values_untouched(self):
        self._apply(enhancements=False)
        with netCDF4.Dataset(self.proc) as ds:
            self.assertTrue(np.array_equal(np.asarray(ds.variables["max_hole_diameter"][:]),
                                           MAX_HOLE))
            self.assertTrue(np.array_equal(np.asarray(ds.variables["edge_at_max_hole"][:]),
                                           EDGE))

    def test_on_still_leaves_the_PORT_s_own_files_byte_identical(self):
        """The ON arm is additive. Every applier copies its source and writes a separate
        ``.enh.*`` file; the faithful output and its stamp are what a flagless run produces,
        byte for byte. An applier that corrected in place would be a fidelity defect."""
        if not _HAVE_ENHANCEMENTS:
            self.skipTest("arrayprobe_enhancements not installed")
        before = _digest(self.out)
        self._apply(enhancements=True)
        after = _digest(self.out)
        for name, payload in before.items():
            self.assertIn(name, after, f"the ON arm removed {name}")
            self.assertEqual(after[name], payload,
                             f"the ON arm rewrote the port's own {name}")


class TheFlagOnActuallyApplies(_Fixture):
    """Property 2, the one that fails without the change. Asserted on a value that moved in a
    file on disk -- not on a log line, and not on a provenance sidecar, both of which a driver
    can emit while applying nothing (which is exactly what this driver did until today)."""

    def setUp(self):
        if not _HAVE_ENHANCEMENTS:
            self.skipTest("arrayprobe_enhancements not installed")
        super().setUp()

    def test_the_correction_ran_and_the_values_moved(self):
        rc, log = self._apply(enhancements=True)
        # A proc-stage correction now has its sd rebuilt by the port's own S4. This
        # fixture's proc is a four-column stand-in with no .tas.csv, so the rebuild cannot run,
        # and an incomplete chain is rc 1 with the reason named -- never a silent fall-back to
        # the port's sd. The proc-stage correction itself still ran, asserted below.
        self.assertEqual(rc, 1, log)
        self.assertIn("the chain is incomplete", log)
        enhanced = self.out / f"{self.STEM}.enh.proc.nc"
        self.assertTrue(enhanced.exists(),
                        f"--enhancements wrote no {enhanced.name}; log:\n{log}")
        with netCDF4.Dataset(enhanced) as ds:
            got_max = np.asarray(ds.variables["max_hole_diameter"][:])
            got_edge = np.asarray(ds.variables["edge_at_max_hole"][:])
        # C5: imgProc_sm.m:919-920 writes each column into the other's slot, so the
        # correction is the swap back. Exact equality, not a tolerance -- a relabelling
        # moves values, it does not compute new ones.
        self.assertTrue(np.array_equal(got_max, EDGE),
                        f"max_hole_diameter is {got_max}, not the corrected {EDGE}")
        self.assertTrue(np.array_equal(got_edge, MAX_HOLE),
                        f"edge_at_max_hole is {got_edge}, not the corrected {MAX_HOLE}")
        self.assertFalse(np.array_equal(got_max, MAX_HOLE),
                         "the enhanced file carries the port's own values: nothing was applied")

    def test_the_enhanced_product_says_so_in_its_own_call_stamp(self):
        """Item 3. A product processed with enhancements must say so where the next person
        looks -- otherwise two files in one directory hold numbers from two different arms and
        nothing distinguishes them, which is what made a week of ARM numbers unquotable."""
        self._apply(enhancements=True)
        enhanced = self.out / f"{self.STEM}.enh.proc.nc"
        stamp = run_flight.read_stamp(enhanced)
        self.assertIsNotNone(stamp, "the enhanced product carries no .call sidecar")
        self.assertIn(run_flight.ENHANCEMENTS_STAMP_KEY, stamp)
        self.assertIn("hole_edge_swap", stamp)
        # It carries the whole configuration the port ran under as well, because the arm is
        # only half of what makes a number traceable.
        self.assertTrue(stamp.startswith(run_flight.proc_call_label()),
                        f"the enhanced stamp does not begin with the source product's: {stamp}")
        # ... and the port's own product does NOT carry the fragment, or the two would again
        # be indistinguishable.
        self.assertNotIn(run_flight.ENHANCEMENTS_STAMP_KEY,
                         run_flight.read_stamp(self.proc) or "")

    def test_the_provenance_record_names_what_ran(self):
        self._apply(enhancements=True)
        import json
        record = json.loads((self.out / f"{self.sd.name}.enhancements.json").read_text())
        self.assertIn("hole_edge_swap", record["applied"])
        self.assertEqual(record["outputs"]["hole_edge_swap"], f"{self.STEM}.enh.proc.nc")


class TheDriverRefusesRatherThanGuesses(_Fixture):
    def test_no_config_is_a_named_refusal(self):
        args = _Args(self.out, None, enhancements=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_flight.apply_enhancements_to_run(args, [self.STEM])
        self.assertEqual(rc, 1)
        self.assertIn("needs --config", buf.getvalue())

    def test_a_config_naming_nothing_applies_nothing(self):
        if not _HAVE_ENHANCEMENTS:
            self.skipTest("arrayprobe_enhancements not installed")
        self.config.write_text('[fidelity]\nprofile = "ORACLES_PRODUCTION"\n[enhancements]\n',
                               encoding="utf-8")
        before = _digest(self.out)
        rc, log = self._apply(enhancements=True)
        self.assertEqual(rc, 0)
        self.assertIn("nothing to", log)
        self.assertEqual(_digest(self.out), before)


class ThePortIsStillNotCoupledToTheEnhancements(unittest.TestCase):
    """Property 3. ``tests/test_no_enhancement_coupling.py`` sweeps ``src/arrayprobe/`` and must
    stay green; the driver half is here, because ``scripts/`` is not swept by it -- the guard there
    is that the reference is ``ImportError``-guarded, so the port's own venv without the optional
    package gets a refusal line rather than a traceback."""

    def test_the_existing_coupling_sweep_is_still_green(self):
        """Delegated, never re-implemented: ``test_no_enhancement_coupling`` is the control, and
        a second hand-rolled copy here would be a second thing to keep correct -- a first draft
        of exactly that copy passed ``triage_server.py``'s two legitimately *guarded* imports as
        violations. ``cli.py`` forwards ``--enhancements`` as a string into the driver's argv and
        imports nothing, so the sweep is unmoved by this change; running it here records that as
        a fact of this feature rather than a hope."""
        # Imported both ways on purpose. The suite is discovered as
        # ``tests.test_*`` from ``python_port/``, where the bare name does not
        # resolve; a bare-name-only import passed when this module was run
        # directly and failed under `discover`, which is the invocation that
        # actually gates a commit.
        try:
            from tests import test_no_enhancement_coupling as coupling
        except ImportError:  # run from inside tests/, or with it on the path
            import test_no_enhancement_coupling as coupling
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(
            coupling.NoEnhancementCouplingTests)
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful(),
                        f"the port/enhancements coupling sweep broke: "
                        f"{result.failures + result.errors}")

    def test_the_driver_s_import_is_guarded(self):
        import ast
        tree = ast.parse(driver_source("run_flight.py").read_text(encoding="utf-8"))
        guarded, unguarded = [], []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            catches_import = any(
                h.type is None
                or (isinstance(h.type, ast.Name) and h.type.id in
                    ("ImportError", "ModuleNotFoundError"))
                for h in node.handlers)
            for child in ast.walk(node):
                if isinstance(child, ast.ImportFrom) and child.module == "arrayprobe_enhancements":
                    (guarded if catches_import else unguarded).append(child.lineno)
        self.assertTrue(guarded,
                        "scripts/run_flight.py no longer imports arrayprobe_enhancements at all: "
                        "--enhancements cannot be doing anything")
        self.assertEqual(unguarded, [],
                         "an unguarded enhancements import in the driver -- the port's own venv "
                         "without the optional package would get a traceback, not a refusal")


if __name__ == "__main__":
    unittest.main()
