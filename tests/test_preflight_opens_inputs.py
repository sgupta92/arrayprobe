# SPDX-License-Identifier: BSD-3-Clause
"""The preflight opens every input, and it FIRES on the one that cost 754 s.

**The incident, 2026-09-20.** A long run died with ``KeyError: 'TAS'`` after
the whole S2 decode had already finished -- 754 seconds in -- because the
aircraft file it was handed does not carry UIOOPS's ``TAS``/``Time`` pair and
nothing had opened it before the run started. Every fact needed to refuse the
run was on disk in its first second.

``scripts/preflight_inputs.py``
is the check. This is the test that makes it
**fire**: a netCDF file written by the port's own ``ncio``, carrying real
variables but not a true-airspeed pair, must be refused -- with the names it
does carry in the message, so the next person adds a variant from evidence
rather than from a hunch.

**A guard must be executed, not read** (this
project's four dead guards). So the assertions here are: it refuses the bad
file; it accepts each name pair the driver itself accepts; it accepts a
named-but-absent ``--iat-file``, because ``sizeDist.m:65`` does and the
archived ORACLES product was made that way; and its table of accepted names
is checked against ``run_flight.py``'s own ``_TAS_VARIANTS``, read out of that
file's source, so the two copies cannot drift into a preflight that passes
what the run then rejects.
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

from tests._driver import driver_source

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "scripts"
sys.path.insert(0, str(ROOT / "src"))

from arrayprobe import ncio  # noqa: E402


def _load_preflight():
    spec = importlib.util.spec_from_file_location(
        "preflight_inputs", TOOLS / "preflight_inputs.py")
    mod = importlib.util.module_from_spec(spec)
    # Registered before exec: the module defines a dataclass, and
    # ``dataclasses`` resolves annotations through ``sys.modules[__module__]``.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


preflight = _load_preflight()


def _write_nc(path: Path, names: list[str]) -> None:
    """A real netCDF file, written by the port's own writer, carrying ``names``."""
    f = ncio.create(str(path))
    dim = ncio.def_dim(f, "n", 3)
    for name in names:
        ncio.def_var(f, name, "double", [dim])
    ncio.end_def(f)
    ncio.close(f)


class ThePreflightFires(unittest.TestCase):
    """The 754-second failure, caught in the first second instead."""

    def test_an_aircraft_file_with_no_true_airspeed_pair_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tas = Path(td) / "no_tas.nc"
            _write_nc(tas, ["airspeed_kts", "seconds"])
            problems = preflight.check_tas_file(tas)
        self.assertEqual(
            1, len(problems),
            "the file carries no TAS/Time pair and no accepted variant; the "
            "preflight must refuse it -- this is the exact file shape that "
            "raised KeyError: 'TAS' 754 s into a run on 2026-09-20")
        why = problems[0].why
        self.assertIn("airspeed_kts", why,
                      "the refusal must name what the file DOES carry, or the "
                      "next person guesses a variant instead of reading one")
        self.assertIn("do not guess a name", why)

    def test_the_cli_exits_2_and_says_so(self) -> None:
        """The firing path a launcher would actually take."""
        with tempfile.TemporaryDirectory() as td:
            tas = Path(td) / "no_tas.nc"
            _write_nc(tas, ["airspeed_kts", "seconds"])
            raw = Path(td) / "flight.2DS"
            raw.write_bytes(b"\x00" * 16)
            code = preflight.main([str(raw), "--tas-file", str(tas)])
        self.assertEqual(2, code, "an unreadable input must refuse the launch")

    def test_a_missing_raw_file_is_refused(self) -> None:
        problems = preflight.check_inputs(raws=[str(ROOT / "nope.2DS")])
        self.assertEqual(1, len(problems))
        self.assertIn("does not exist", problems[0].why)

    def test_an_empty_raw_file_is_refused(self) -> None:
        """Zero bytes opens fine and decodes to nothing -- the silent case."""
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "empty.2DS"
            raw.write_bytes(b"")
            problems = preflight.check_inputs(raws=[str(raw)])
        self.assertEqual(1, len(problems))
        self.assertIn("empty", problems[0].why)

    def test_an_iat_file_without_threshold_is_refused(self) -> None:
        """``sizedist.py:1409-1411`` reads ``threshold`` by name, deep in S4."""
        with tempfile.TemporaryDirectory() as td:
            iat = Path(td) / "thresh.nc"
            _write_nc(iat, ["intarr"])
            problems = preflight.check_iat_file(iat)
        self.assertEqual(1, len(problems))
        self.assertIn("threshold", problems[0].why)


class ThePreflightDoesNotRefuseWhatTheRunAccepts(unittest.TestCase):
    """A preflight that over-refuses gets skipped, and then guards nothing."""

    def test_each_accepted_variant_passes(self) -> None:
        for tas_name, time_name in preflight.TAS_VARIANTS:
            with self.subTest(pair=f"{tas_name}/{time_name}"):
                with tempfile.TemporaryDirectory() as td:
                    p = Path(td) / "tas.nc"
                    _write_nc(p, [tas_name, time_name])
                    self.assertEqual([], preflight.check_tas_file(p))

    def test_a_named_but_absent_iat_file_is_not_a_problem(self) -> None:
        """``sizeDist.m:65`` sets ``iaThreshFile = 'NONE'`` and carries on.

        The archived ORACLES 2016 product was made with exactly this call --
        ``2DS_intArrThreshold_MISSING.cdf``, which does not exist.
        A preflight that refused it would refuse the
        reproduction of the archived product.
        """
        self.assertEqual(
            [], preflight.check_iat_file(ROOT / "2DS_intArrThreshold_MISSING.cdf"))

    def test_a_writable_out_dir_passes_and_leaves_nothing_behind(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "made" / "here"
            self.assertEqual([], preflight.check_out_dir(out))
            self.assertTrue(out.is_dir())
            self.assertEqual([], list(out.iterdir()),
                             "the write probe must be cleaned up")

    def test_clean_inputs_report_as_clean(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "flight.2DS"
            raw.write_bytes(b"\x00" * 16)
            tas = Path(td) / "tas.nc"
            _write_nc(tas, ["TAS", "Time"])
            self.assertEqual(
                0, preflight.main([str(raw), "--tas-file", str(tas),
                                   "--out", str(Path(td) / "out")]))


class TheTwoCopiesOfTheVariantTableAgree(unittest.TestCase):
    """The drift this second copy would otherwise introduce.

    ``run_flight._aircraft_series`` tries ``_TAS_VARIANTS``; the preflight
    tries :data:`preflight_inputs.TAS_VARIANTS`. If those ever disagree the
    preflight either passes a file the run rejects (the failure it exists to
    prevent, now with a green light in front of it) or refuses one the run
    accepts. Read from ``run_flight.py``'s SOURCE rather than by importing it,
    the way ``test_worker_argument_forwarding.py`` reads the CLI's flag list:
    the driver is a script with a heavy import, and the two sides of a check
    must come from different places.
    """

    def test_the_preflight_accepts_exactly_what_the_driver_accepts(self) -> None:
        source = driver_source("run_flight.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        found = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "_TAS_VARIANTS"
                            for t in node.targets)):
                found = node.value
                break
        self.assertIsNotNone(
            found, "run_flight.py no longer defines _TAS_VARIANTS at module "
                   "level; the preflight's copy is now unchecked")
        # The driver derives its table from tas_sources.SOURCES rather than
        # writing a literal; assert that derivation from the source text, and hold the
        # preflight's copy to the same registry.
        iters = [ast.unparse(g.iter) for g in ast.walk(found)
                 if isinstance(g, ast.comprehension)]
        self.assertEqual(iters, ["_tas_sources.SOURCES"],
                         "run_flight._TAS_VARIANTS no longer derives from "
                         "tas_sources.SOURCES")
        from arrayprobe.tools import tas_sources
        driver_pairs = tuple((s.tas_var, s.time_var) for s in tas_sources.SOURCES)
        self.assertEqual(
            driver_pairs, tuple(preflight.TAS_VARIANTS),
            "scripts/preflight_inputs.py's TAS_VARIANTS has drifted from "
            "run_flight.py's _TAS_VARIANTS. Update both, and only from a name "
            "read off a real file")



class TheDriverRunsIt(unittest.TestCase):
    """``run_flight.preflight`` calls this module (the preflight's wiring into the driver), so a
    bad --tas-file refuses the run before the decode rather than 754 s into it."""

    def setUp(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "run_flight", ROOT / "scripts" / "run_flight.py")
        assert spec is not None and spec.loader is not None
        if "run_flight" not in sys.modules:
            mod = importlib.util.module_from_spec(spec)
            sys.modules["run_flight"] = mod
            spec.loader.exec_module(mod)
        self.rf = sys.modules["run_flight"]
        self.addCleanup(setattr, self.rf, "TAS_FILE", self.rf.TAS_FILE)

    def _preflight(self, names: list[str]) -> bool:
        with tempfile.TemporaryDirectory() as td:
            tas = Path(td) / "tas.nc"
            _write_nc(tas, names)
            self.rf.TAS_FILE = str(tas)
            (Path(td) / "out").mkdir()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ok = self.rf.preflight([], Path(td) / "out",
                                       iat_file=str(ROOT / "2DS_intArrThreshold_MISSING.cdf"))
            self.out = buf.getvalue()
            return ok

    def test_a_tas_file_without_uiops_names_is_refused(self) -> None:
        self.assertFalse(self._preflight(["airspeed", "seconds"]))
        self.assertIn("REFUSED", self.out)

    def test_a_good_tas_file_and_the_missing_iat_file_pass(self) -> None:
        self.assertTrue(self._preflight(["TAS", "Time"]), self.out)

    def _raw_preflight(self, payload: bytes) -> bool:
        self.rf.TAS_FILE = None
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "base000000000000.2DS"
            raw.write_bytes(payload)
            (Path(td) / "out").mkdir()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ok = self.rf.preflight([raw], Path(td) / "out",
                                       iat_file=str(ROOT / "2DS_intArrThreshold_MISSING.cdf"))
            self.out = buf.getvalue()
            return ok

    def test_an_empty_raw_file_is_refused_before_stage_2(self) -> None:
        # Input preflight: the raw files reach check_inputs, so a 0-byte raw
        # is refused at preflight.
        self.assertFalse(self._raw_preflight(b""))
        self.assertIn("REFUSED", self.out)
        self.assertIn("is empty", self.out)

    def test_a_non_empty_raw_file_passes_the_input_check(self) -> None:
        self.assertTrue(self._raw_preflight(b"\x00" * 4096), self.out)
        self.assertNotIn("REFUSED", self.out)

    def test_a_missing_raw_file_fails_the_preflight(self) -> None:
        # check_inputs is handed only the raws that exist; a missing one must still fail the
        # preflight (the MISSING line), never pass because the input check never saw it.
        self.rf.TAS_FILE = None
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "out").mkdir()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ok = self.rf.preflight([Path(td) / "base000000000000.2DS"], Path(td) / "out",
                                       iat_file=str(ROOT / "2DS_intArrThreshold_MISSING.cdf"))
        self.assertFalse(ok, buf.getvalue())
        self.assertIn("MISSING", buf.getvalue())
        self.assertIn("NOT OK", buf.getvalue())

if __name__ == "__main__":  # pragma: no cover
    unittest.main()
