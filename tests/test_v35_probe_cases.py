# SPDX-License-Identifier: BSD-3-Clause
"""Registered probe cases .

The mechanism under test: a run may name a registered
:class:`arrayprobe_uiops.probe_cases.ProbeCase` for S4's bin ladder and the
constants beside it, because v3.5's ``switch`` has no case for a campaign
upstream never wrote one for -- and its ``otherwise``/``'2DS'`` case hands a
2D-S the **HVPS** ladder, which empties the size distribution.

Four things are asserted here, and the first two are the ones that matter:

1. **The vendored tables are not "fixed".**  ``probe_defaults()`` still returns
   v3.5's 28-bin HVPS table for an unlisted campaign's 2D-S, for ever.
2. **A run that names no case is bit-identical** to one that could not have
   named one -- ``np.array_equal`` over every variable of a real S4 output, not
   ``allclose``.
3. A named case actually changes the ladder, and the ARM case's is v3.1.4's.
4. Every field of a case cites a vendored ``file:line``, mechanically.
"""

from __future__ import annotations

import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

import netCDF4
import numpy as np
from tests import _upstream
from tests._repo import needs_v314_engine, repo_only

from arrayprobe_uiops import sizedist as sizedist_v35
from arrayprobe_uiops.probe_cases import (
    PROBE_CASES,
    ProbeCase,
    UncitedProbeCaseField,
    UnknownProbeCase,
    resolve_probe_case,
)
from arrayprobe_uiops.sizedist_tables import (
    OTHERWISE,
    V35_TABLES,
    ProbeDefaults,
    probe_defaults,
)


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


#: The ARM ENA registration modules are development-only: a distribution may
#: ship without them, and the tests that exercise those cases skip there. The
#: mechanism tests (bit-identity, citations, refusals, the stamp) need neither.
_needs_arm_ena = unittest.skipUnless(
    _has_module("arrayprobe_uiops.register_arm_ena_2ds")
    and _has_module("arrayprobe_uiops.register_arm_ena_2ds_cold"),
    "arrayprobe_uiops.register_arm_ena_2ds: the ARM ENA registration module is not in "
    "this distribution",
)


def register_arm_ena_2ds():
    """Imported on use, so this module loads where the ARM ENA module does not ship."""
    from arrayprobe_uiops.register_arm_ena_2ds import register_arm_ena_2ds as _register

    return _register()

DATA = Path(__file__).resolve().parent / "data"
PROC = DATA / "demo_flight_v35_proc.nc"

#: An unlisted campaign: the point of the whole exercise is what happens in the
#: ``otherwise`` branch, and ARM's own preset declares exactly this name.
UNLISTED = "ARM_ENA"

#: "the caller did not pass the argument at all", as every caller before probe cases
#: called ``run()``. Distinct from ``None``, which is what ``run_flight.py``
#: passes on a run that names no case -- the two must reach the same code, and
#: collapsing them here would make the bit-identity test below compare a call
#: with itself.
_OMIT = object()


def _s4(outfile: Path, *, probe_case=_OMIT, projectname: str = UNLISTED):
    """One real S4 on the tracked v3.5 demo proc file.

    ``probe_case`` is passed positionally-by-keyword exactly as
    ``scripts/run_flight.py`` passes it, so the default path this test pins is the
    same code the driver runs.
    """
    with netCDF4.Dataset(str(PROC)) as ds:
        t = np.asarray(ds.variables["Time"][:], dtype=np.float64).reshape(-1)
    # A TAS series covering the proc's own seconds. Synthetic and constant: this
    # test is about which bin ladder S4 uses, and a constant airspeed removes
    # airspeed as a variable between the two runs being compared.
    timehhmmss = np.unique(np.floor(t))
    tas = np.full_like(timehhmmss, 100.0)
    kwargs = {} if probe_case is _OMIT else {"probe_case": probe_case}
    sizedist_v35.run(
        str(PROC), str(outfile), tas, timehhmmss, "2DS", 6, 2,
        np.full_like(tas, 85000.0), np.full_like(tas, -5.0),
        0, 0, 0, 0, projectname, "20170707 000000",
        software="UIOOPS_v3.5", creation_time="fixed-for-the-test",
        **kwargs,
    )


def _variables(path: Path) -> dict[str, np.ndarray]:
    with netCDF4.Dataset(str(path)) as ds:
        return {k: np.asarray(v[:]) for k, v in ds.variables.items()}


class TestTheVendoredTableIsUntouched(unittest.TestCase):
    """The defect is upstream's and stays reproduced."""

    def test_an_unlisted_campaigns_2ds_still_gets_the_hvps_ladder_on_v35(self):
        cfg = probe_defaults(UNLISTED, "2DS", version="3.5")
        self.assertEqual(cfg.num_bins, 28)
        kk = cfg.kk()
        self.assertEqual(kk[0], 0.2)
        self.assertEqual(kk[-1], 30.0)

    def test_v314_has_the_10um_ladder_for_the_same_case(self):
        # sizeDist.m:374,:376 in UIOPS-v3.1.4/joefinlon-UIOPS-ba5e67c/ -- the
        # source of the ARM case's two borrowed fields.
        cfg = probe_defaults(UNLISTED, "2DS", version="3.1.4")
        self.assertEqual(cfg.num_bins, 128)
        self.assertAlmostEqual(cfg.kk()[0], 0.005)
        self.assertAlmostEqual(cfg.kk()[-1], 1.285)


class TestDefaultIsBitIdentical(unittest.TestCase):
    """Opt-in, default-off: naming no case must change no written byte."""

    def test_no_probe_case_equals_no_probe_case_argument(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td) / "a.nc", Path(td) / "b.nc"
            _s4(a)                      # as every caller before probe cases called it
            _s4(b, probe_case=None)     # as scripts/run_flight.py calls it now
            va, vb = _variables(a), _variables(b)
        self.assertEqual(sorted(va), sorted(vb))
        for name in va:
            self.assertTrue(
                np.array_equal(va[name], vb[name], equal_nan=True),
                f"{name} is not bit-identical between a run that named no probe case and "
                "one that passed probe_case=None; the default path is supposed to be the "
                "untouched switch lookup",
            )

    def test_the_default_run_used_the_switchs_own_28_bin_ladder(self):
        # The identity above would also hold if BOTH runs were broken the same
        # way, so this side names the number: the default is still upstream's.
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "a.nc"
            _s4(out)
            with netCDF4.Dataset(str(out)) as ds:
                self.assertEqual(ds.variables["bin_min"].shape[0], 28)
                self.assertEqual(float(ds.variables["bin_min"][0]), 0.2)


@_needs_arm_ena
class TestArmEnaCase(unittest.TestCase):
    def setUp(self):
        self.case = register_arm_ena_2ds()

    def test_it_differs_from_stock_v35_in_exactly_two_fields(self):
        stock = V35_TABLES[OTHERWISE]["2DS"]
        moved = [
            f for f in ProbeDefaults.__dataclass_fields__
            if getattr(stock, f) != getattr(self.case.defaults, f)
        ]
        self.assertEqual(sorted(moved), ["bins", "num_bins"])

    def test_its_ladder_is_v314s_own_line_for_the_same_case(self):
        v314 = probe_defaults(UNLISTED, "2DS", version="3.1.4")
        self.assertEqual(self.case.defaults.num_bins, v314.num_bins)
        self.assertTrue(np.array_equal(self.case.defaults.kk(), v314.kk()))

    def test_a_run_on_the_case_gets_128_bins(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "arm.nc"
            _s4(out, probe_case="arm-ena-2ds")
            with netCDF4.Dataset(str(out)) as ds:
                self.assertEqual(ds.variables["bin_min"].shape[0], 128)
                self.assertAlmostEqual(float(ds.variables["bin_min"][0]), 0.005)

    def test_registering_twice_is_a_no_op(self):
        again = register_arm_ena_2ds()
        self.assertEqual(again.defaults, self.case.defaults)
        self.assertIs(resolve_probe_case("arm-ena-2ds"), again)

    def test_the_registration_module_registers_it(self):
        import importlib

        importlib.import_module("arrayprobe_uiops.register_arm_ena_2ds")
        self.assertIn("arm-ena-2ds", PROBE_CASES)


_REPO = Path(__file__).resolve().parents[1]


def _source_lines(path: str) -> list[str]:
    """The vendored file split on newline only, so line N is what ``sed -n Np`` prints."""
    text = _upstream.cited_path(path).read_text(encoding="utf-8", errors="replace")
    return [ln.rstrip("\r") for ln in text.split("\n")]


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _citation_problem(field: str, citation: str) -> str | None:
    """Why ``path:N -- text`` (or ``path:A-B -- prose``) misstates its source, or None.

    A single line must contain the quoted text up to any parenthetical aside,
    whitespace ignored. A range must open on a ``case`` line and end on the last
    non-blank line before the next ``case``: the whole block, no more, no less.
    """
    m = re.fullmatch(r"(\S+?):(\d+)(?:-(\d+))? -- (.+)", citation, flags=re.S)
    if m is None:
        return f"{field}: {citation!r} is not 'path:line -- text'"
    path, lo, hi, text = m.group(1), int(m.group(2)), m.group(3), m.group(4)
    lines = _source_lines(path)
    if hi is None:
        quote = text.split(" (", 1)[0]
        if _squash(quote) not in _squash(lines[lo - 1]):
            return f"{field}: {path}:{lo} is {lines[lo - 1].strip()!r}, not {quote!r}"
        return None
    hi_n = int(hi)
    if not lines[lo - 1].lstrip().startswith("case "):
        return f"{field}: {path}:{lo} does not open a case: {lines[lo - 1].strip()!r}"
    nxt = next(i for i in range(lo, len(lines))
               if re.match(r"\s*(case |otherwise\b|end\b)", lines[i]))
    last = max(i for i in range(lo - 1, nxt) if lines[i].strip()) + 1
    if hi_n != last:
        return f"{field}: {path}:{lo}-{hi_n} should end at :{last}, the block's last line"
    return None


class TestEveryFieldIsCited(unittest.TestCase):
    """A constant nobody can cite is an invented constant."""

    @_needs_arm_ena
    @repo_only
    def test_the_arm_case_cites_every_field_at_a_vendored_file_line(self):
        case = register_arm_ena_2ds()
        self.assertEqual(
            set(case.citations), set(ProbeDefaults.__dataclass_fields__)
        )
        for field, citation in case.citations.items():
            path = citation.split(":")[0]
            self.assertTrue(
                _upstream.cited_path(path).is_file(),
                f"{field} cites {path!r}, which is not a file in this repository",
            )
            self.assertTrue(
                path.startswith(("UIOPS-v3.1.4/", "UIOPS-v3.5/")),
                f"{field} cites {path!r}, which is not a vendored UIOPS tree",
            )

    @_needs_arm_ena
    @repo_only  # reads a repository-only file, not in the sdist
    def test_every_cited_line_holds_the_quoted_text(self):
        """The line a citation names must carry the text it quotes.

        Ten of the case's fifteen line references had drifted two lines early
        against the vendored file while the existence check above passed; this is
        the check that reads the line.
        """
        case = register_arm_ena_2ds()
        problems = [
            p for field, citation in case.citations.items()
            if (p := _citation_problem(field, citation))
        ]
        self.assertEqual(problems, [])

    @_needs_arm_ena
    @repo_only  # reads a repository-only file, not in the sdist
    def test_the_parenthetical_v35_references_hold_their_lines(self):
        case = register_arm_ena_2ds()
        v35 = "UIOPS-v3.5/joefinlon-UIOPS-039be82/sizeDist.m"
        for field, want in (("num_bins", "num_bins = 28"),
                            ("bins", "%kk=diodesize/2:diodesize:(num_bins+0.6)*diodesize")):
            m = re.search(r"\(.*:(\d+)", case.citations[field], flags=re.S)
            self.assertIsNotNone(m, field)
            line = _source_lines(v35)[int(m.group(1)) - 1]
            self.assertIn(_squash(want), _squash(line), field)

    @repo_only  # reads a repository-only file, not in the sdist
    def test_a_wrong_line_number_is_caught(self):
        v35 = "UIOPS-v3.5/joefinlon-UIOPS-039be82/sizeDist.m"
        self.assertIsNone(_citation_problem("x", f"{v35}:514 -- applyIntArrThresh = 0"))
        self.assertIsNotNone(_citation_problem("x", f"{v35}:512 -- applyIntArrThresh = 0"))
        self.assertIsNotNone(_citation_problem("x", f"{v35}:497-518 -- the case block"))

    def test_an_uncited_field_is_refused(self):
        with self.assertRaises(UncitedProbeCaseField):
            ProbeCase(
                name="uncited",
                description="x",
                defaults=V35_TABLES[OTHERWISE]["2DS"],
                citations={"num_bins": "UIOPS-v3.5/joefinlon-UIOPS-039be82/sizeDist.m:502"},
            )

    def test_a_citation_for_a_field_that_does_not_exist_is_refused(self):
        full = {f: "UIOPS-v3.5/joefinlon-UIOPS-039be82/sizeDist.m:497"
                for f in ProbeDefaults.__dataclass_fields__}
        with self.assertRaises(UncitedProbeCaseField):
            ProbeCase("x", "x", V35_TABLES[OTHERWISE]["2DS"], {**full, "not_a_field": "x:1"})


class TestUnknownCase(unittest.TestCase):
    def test_an_unregistered_name_says_how_to_register_it(self):
        with self.assertRaises(UnknownProbeCase) as cm:
            resolve_probe_case("no-such-case-9f3a")
        self.assertIn("register_probe_case", str(cm.exception))


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# The driver half: the .call stamp, and the two refusals.
# ---------------------------------------------------------------------------

import sys  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("run_flight", _ROOT / "scripts" / "run_flight.py")
assert _spec is not None and _spec.loader is not None
run_flight = importlib.util.module_from_spec(_spec)
sys.modules.setdefault(_spec.name, run_flight)
_spec.loader.exec_module(run_flight)

from tests import _run_flight_state  # noqa: E402


class TestTheStampRecordsTheCase(unittest.TestCase):
    """A product built on a registered case must be distinguishable from one
    built on v3.5's own switch -- they are different science on the same raw
    bytes; every stage stamps its configuration."""

    def setUp(self):
        self._saved = {n: getattr(run_flight, n) for n in ("ENGINE", "PROBE_CASE", "TAS_FILE")}
        run_flight.ENGINE = "3.5"
        run_flight.TAS_FILE = None

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(run_flight, name, value)

    def test_a_named_case_is_in_the_sd_stamp(self):
        run_flight.PROBE_CASE = "arm-ena-2ds"
        self.assertIn("probe_case=arm-ena-2ds", run_flight.sd_call_label(None))

    def test_no_case_leaves_the_stamp_exactly_as_it_was(self):
        # An unconditional `probe_case=stock` key would make every v3.5 sd file
        # written before probe cases read as stale against its own stamp.
        run_flight.PROBE_CASE = None
        self.assertNotIn("probe_case", run_flight.sd_call_label(None))

    def test_the_two_stamps_differ(self):
        run_flight.PROBE_CASE = None
        stock = run_flight.sd_call_label(None)
        run_flight.PROBE_CASE = "arm-ena-2ds"
        self.assertNotEqual(stock, run_flight.sd_call_label(None))


class TestTheWorkerCarriesBoth(unittest.TestCase):
    """``--jobs``: the NAME alone resolves nowhere in a fresh process, so the
    module has to travel with it (probe_cases.py's module docstring)."""

    def test_spawn_worker_forwards_the_case_and_its_module(self):
        import shutil
        import types
        from unittest import mock

        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        ns = types.SimpleNamespace(
            stages="234", out=root, chunks=1, s2_jobs=1, iat_file="",
            preset="DEMO_2DS_H", tas_file=None, presets=None, config=None,
            allow_mixed_config=False, accept_unstamped=False, diode_corrected=False,
            engine="3.5", worker_stall_min=30.0, profile="stock-v3.5",
            probe_case="arm-ena-2ds",
            probe_case_module="arrayprobe_uiops.register_arm_ena_2ds",
        )
        with mock.patch.object(run_flight.subprocess, "Popen",
                               return_value=mock.Mock()) as popen:
            _proc, log_f = run_flight._spawn_worker([root / "a.2DS"], ns,
                                                    root / "worker.log")
        log_f.close()   # _spawn_worker hands the open handle back to its caller
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[cmd.index("--probe-case") + 1], "arm-ena-2ds")
        self.assertEqual(cmd[cmd.index("--probe-case-module") + 1],
                         "arrayprobe_uiops.register_arm_ena_2ds")

    def test_a_worker_gets_neither_flag_when_the_parent_named_no_case(self):
        import shutil
        import types
        from unittest import mock

        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        ns = types.SimpleNamespace(
            stages="234", out=root, chunks=1, s2_jobs=1, iat_file="",
            preset="DEMO_2DS_H", tas_file=None, presets=None, config=None,
            allow_mixed_config=False, accept_unstamped=False, diode_corrected=False,
            engine="3.5", worker_stall_min=30.0, profile="stock-v3.5",
            probe_case=None, probe_case_module=None,
        )
        with mock.patch.object(run_flight.subprocess, "Popen",
                               return_value=mock.Mock()) as popen:
            _proc, log_f = run_flight._spawn_worker([root / "a.2DS"], ns,
                                                    root / "worker.log")
        log_f.close()
        cmd = popen.call_args.args[0]
        self.assertNotIn("--probe-case", cmd)
        self.assertNotIn("--probe-case-module", cmd)


class TestTheRefusalsHappenAtPreflight(unittest.TestCase):
    """A run that cannot resolve its own ladder must die before the decode, not
    after it: an S2 decode of a real ARM file is ~750 s (STATUS, 2026-09-21)."""

    def setUp(self):
        # main() rebinds ENGINE, PROFILE, PROBE_CASE, PROBE_CASE_MODULE ...;
        # restore every UPPER_CASE global so no later module inherits them.
        _run_flight_state.preserve(self, run_flight)

    def _main(self, extra):
        return run_flight.main([
            "--engine", "3.5", "--profile", "stock-v3.5",
            "--preset", "ORACLES_2016_2DS_H", *extra, "nosuch-raw.2DS",
        ])

    def test_an_unregistered_case_exits_2(self):
        self.assertEqual(self._main(["--probe-case", "no-such-case-9f3a"]), 2)

    @needs_v314_engine
    def test_a_case_under_engine_314_exits_2(self):
        rc = run_flight.main([
            "--engine", "3.1.4", "--port-validation", "--preset", "ORACLES_2016_2DS_H",
            "--probe-case", "arm-ena-2ds", "nosuch-raw.2DS",
        ])
        self.assertEqual(rc, 2)

    def test_the_registration_module_makes_it_resolve(self):
        # The case resolves, so the probe-case refusal is NOT the one that
        # fires: the run proceeds past it and fails on the missing raw file
        # like any other run would. Asserted on what was logged rather than on
        # the exit code, because several unrelated refusals also exit 2 and an
        # exit-code assertion here would pass for the wrong reason. The case is
        # synthetic (the shipped ladder-fix case's defaults and citations under a
        # fresh name) and its registration module is written to a temporary
        # directory, so nothing but --probe-case-module can have registered it.
        import shutil
        import sys as _sys
        import uuid
        from io import StringIO
        from unittest import mock

        from arrayprobe_uiops.probe_cases import register_v35_2ds_ladder_fix

        base = register_v35_2ds_ladder_fix()
        tag = uuid.uuid4().hex[:12]
        name, module = f"synthetic-case-{tag}", f"_register_synthetic_case_{tag}"
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / f"{module}.py").write_text(
            "from arrayprobe_uiops.probe_cases import ProbeCase, register_probe_case, "
            "register_v35_2ds_ladder_fix\n"
            "_base = register_v35_2ds_ladder_fix()\n"
            f"register_probe_case(ProbeCase(name={name!r}, description='synthetic', "
            "defaults=_base.defaults, citations=dict(_base.citations)))\n",
            encoding="utf-8",
        )
        self.addCleanup(_sys.modules.pop, module, None)
        from arrayprobe_uiops import probe_cases as _pc

        self.addCleanup(_pc._REGISTRY.pop, name, None)
        with mock.patch.object(_sys, "path", [str(root), *_sys.path]):
            # Without the module the same name is refused, so the assertion
            # below is about the module and not about the name.
            buf = StringIO()
            with mock.patch("sys.stdout", buf):
                self._main(["--probe-case", name])
            self.assertIn("no probe case", buf.getvalue())

            buf = StringIO()
            with mock.patch("sys.stdout", buf):
                self._main(["--probe-case", name, "--probe-case-module", module])
            self.assertNotIn("no probe case", buf.getvalue())
        self.assertEqual(resolve_probe_case(name).defaults, base.defaults)

    def test_an_unregistered_name_is_refused_before_any_decode(self):
        from io import StringIO
        from unittest import mock

        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            self._main(["--probe-case", "no-such-case-9f3a"])
        out = buf.getvalue()
        self.assertIn("no probe case", out)
        self.assertIn("--probe-case-module", out)
        self.assertNotIn("S2 start", out)


@_needs_arm_ena
class TestArmEnaColdCase(unittest.TestCase):
    """``arm-ena-2ds-cold``: ``arm-ena-2ds`` with v3.5's own gate-on 2D-S shattering pair."""

    def setUp(self):
        from arrayprobe_uiops.register_arm_ena_2ds_cold import register_arm_ena_2ds_cold

        self.warm_before = register_arm_ena_2ds().defaults
        self.cold = register_arm_ena_2ds_cold()
        self.warm = register_arm_ena_2ds()

    def test_it_differs_from_arm_ena_2ds_only_in_the_gate_fields(self):
        moved = [
            f for f in ProbeDefaults.__dataclass_fields__
            if getattr(self.warm.defaults, f) != getattr(self.cold.defaults, f)
        ]
        self.assertEqual(sorted(moved), ["applyIntArrThresh", "defaultIntArrThresh"])
        self.assertEqual(self.cold.defaults.applyIntArrThresh, 1)
        self.assertEqual(self.cold.defaults.defaultIntArrThresh, 1e-6)
        self.assertTrue(np.array_equal(self.cold.defaults.kk(), self.warm.defaults.kk()))

    def test_registering_it_leaves_arm_ena_2ds_as_it_was(self):
        self.assertEqual(self.warm.defaults, self.warm_before)
        self.assertEqual(self.warm.defaults.applyIntArrThresh, 0)
        self.assertEqual(self.warm.defaults.defaultIntArrThresh, 4e-6)
        self.assertIs(resolve_probe_case("arm-ena-2ds"), self.warm)

    def test_only_the_gate_citations_differ(self):
        moved = sorted(f for f in self.warm.citations
                       if self.warm.citations[f] != self.cold.citations[f])
        self.assertEqual(moved, ["applyIntArrThresh", "defaultIntArrThresh"])

    @repo_only  # reads a repository-only file, not in the sdist
    def test_it_cites_every_field_and_every_cited_line_holds_its_text(self):
        self.assertEqual(set(self.cold.citations), set(ProbeDefaults.__dataclass_fields__))
        problems = [
            p for field, citation in self.cold.citations.items()
            if (p := _citation_problem(field, citation))
        ]
        self.assertEqual(problems, [])

    @repo_only  # reads a repository-only file, not in the sdist
    def test_the_socrates_lines_named_in_the_asides_hold_the_same_values(self):
        v35 = "UIOPS-v3.5/joefinlon-UIOPS-039be82/sizeDist.m"
        lines = _source_lines(v35)
        for field, want in (("applyIntArrThresh", "applyIntArrThresh = 1"),
                            ("defaultIntArrThresh", "defaultIntArrThresh = 1e-6")):
            m = re.search(r"\(.*:(\d+), SOCRATES", self.cold.citations[field], flags=re.S)
            self.assertIsNotNone(m, field)
            self.assertIn(_squash(want), _squash(lines[int(m.group(1)) - 1]), field)
        # The two cases the citations name are the 2D-S ones of GPM and SOCRATES.
        self.assertEqual(lines[207 - 1].strip(), "case 'GPM'")
        self.assertEqual(lines[209 - 1].strip(), "case '2DS'")
        self.assertEqual(lines[292 - 1].strip(), "case 'SOCRATES'")
        self.assertEqual(lines[294 - 1].strip(), "case '2DS'")

    def test_registering_twice_is_a_no_op(self):
        from arrayprobe_uiops.register_arm_ena_2ds_cold import register_arm_ena_2ds_cold

        again = register_arm_ena_2ds_cold()
        self.assertEqual(again.defaults, self.cold.defaults)
        self.assertIs(resolve_probe_case("arm-ena-2ds-cold"), again)

    def test_the_registration_module_registers_it(self):
        import importlib

        importlib.import_module("arrayprobe_uiops.register_arm_ena_2ds_cold")
        self.assertIn("arm-ena-2ds-cold", PROBE_CASES)
        self.assertIn("arm-ena-2ds", PROBE_CASES)
