# SPDX-License-Identifier: BSD-3-Clause
"""The scientist's guide is written for scientists, and every checkable claim on it is checked.

WHY THIS EXISTS. The independent review of 2026-09-14 (archived report, R1,
section 3, row 7) found the documentation written for
the project's own audit trail -- finding ids, ledger ids and dates in the prose -- and asked for a
two-page guide an atmospheric scientist can read cold. That is
``docs/00a-scientists-guide.md``. A register is exactly the kind of rule that decays
by attention, so it is held here mechanically, in four parts:

1. **Register.** No finding id, stage or lane id (``S2``, ``W4``),
   ledger-style id (letter-number) or date (``2026-09-14``, ``09/06``) anywhere on the
   page. Each pattern is mutation-tested below: inserting one makes the check fire.
2. **Numbers.** Every number in the page's prose is consumed by a declared binding to
   ``paper/paper_numbers.json``, and each bound value must equal the registry's. A number with no
   binding fails -- so a figure typed onto the page later cannot sit there unchecked. Version
   numbers and instrument names (``v3.5``, ``SODA-2``, ``2D-S``) are names, not quantities, and
   are removed by an explicit list first.
3. **Mechanism claims are executed, not read** (the project's guard doctrine). The default
   engine is asked for; the units the page quotes are
   read from the tracked demo size-distribution files both engines wrote; the netCDF format and
   the absence of a ``Conventions`` attribute are read from the same files; the flight product's
   variable names and its lack of attributes come from running the combine; the example
   enhancement must be one the driver can apply on the engine the example names; and the SODA-2
   paragraph is tied to whether the SODA-2 driver still refuses its ASCII size-distribution
   export -- the claim most likely to go stale, because that writer is being ported.
4. **Placement.** The page sorts directly after the index and the index links it.

The page is outside ``python_port/`` and so absent from a source distribution; every test skips
when it is missing rather than failing in a tarball.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

from tests._repo import PKG_ROOT  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PORT = PKG_ROOT
GUIDE = ROOT / "docs" / "00a-scientists-guide.md"
INDEX = ROOT / "docs" / "00-index.md"
REGISTRY = ROOT / "paper" / "paper_numbers.json"
DATA = PORT / "tests" / "data"

_HAVE_GUIDE = GUIDE.is_file() and REGISTRY.is_file()
_WHY = (f"needs {GUIDE.relative_to(ROOT).as_posix()} and "
        f"{REGISTRY.relative_to(ROOT).as_posix()}; missing: "
        + ", ".join(q.relative_to(ROOT).as_posix() for q in (GUIDE, REGISTRY) if not q.is_file()))


def _guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 1. Register
# --------------------------------------------------------------------------

#: What the audit-trail register looks like, one pattern per kind. Deliberately broad: a false
#: positive costs a rewording on a two-page guide, a false negative is the drift this exists for.
REGISTER_PATTERNS = {
    # Finding ids, and stage/lane ids of the same shape (S2, W4, R1, Z5).
    "finding or stage id": re.compile(r"\b[A-Z]{1,2}\d{1,3}[a-z]?\b"),
    # SODA-2 findings: S6-a, S2-b(ii).
    "SODA-2 finding id": re.compile(r"\bS\d-[a-z]\b"),
    # Ledger and decision ids: a letter, a hyphen and a number.
    "ledger id": re.compile(r"\b[A-Z]{1,2}-\d{1,3}\b"),
    "ISO date": re.compile(r"\b(?:19|20)\d{2}-\d{2}(?:-\d{2})?\b"),
    "short date": re.compile(r"\b\d{2}/\d{2}\b"),
}


def register_violations(text: str) -> list[str]:
    out = []
    for kind, pattern in REGISTER_PATTERNS.items():
        for m in pattern.finditer(text):
            line = text[:m.start()].count("\n") + 1
            out.append(f"line {line}: {kind} {m.group(0)!r}")
    return out


# --------------------------------------------------------------------------
# 2. Numbers
# --------------------------------------------------------------------------

#: Tokens that contain digits but are names, not quantities.
NAMES_WITH_DIGITS = re.compile(
    r"\bv?3\.1\.4\b|\bv?3\.5\b|\bSODA-2\b|\b2D-S\b|\b2DC\b|\b2DP\b|\bnetCDF-[34]\b")

#: Every number the guide may state, as (pattern with one group, registry key path). Each must
#: match at least once; each match must equal the registry.
BOUND_NUMBERS = (
    (re.compile(r"\b(\d+) field-campaign flights\b"), ("validation", "flights_validated_total")),
    (re.compile(r"\b(\d+) of them exactly\b"), ("validation", "flights_exact_total")),
)


def _prose(text: str) -> str:
    """The page with fenced code, inline code spans and link targets removed."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", " ", text)
    return re.sub(r"\]\([^)\s]*\)", "]", text)


def _registry(path: tuple[str, ...]):
    v = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for k in path:
        v = v[k]
    return v["value"] if isinstance(v, dict) and "value" in v else v


def number_problems(text: str) -> list[str]:
    prose = NAMES_WITH_DIGITS.sub(" ", _prose(text))
    problems = []
    for pattern, key in BOUND_NUMBERS:
        hits = list(pattern.finditer(prose))
        if not hits:
            problems.append(f"no mention matches {pattern.pattern!r} ({'.'.join(key)}); "
                            "if the sentence was reworded, move the binding with it")
        want = _registry(key)
        for m in hits:
            if int(m.group(1)) != want:
                problems.append(f"{m.group(0)!r} but the registry's {'.'.join(key)} is {want}")
        prose = pattern.sub(" ", prose)
    for m in re.finditer(r"\d+(?:[.,]\d+)*", prose):
        ctx = prose[max(0, m.start() - 30):m.end() + 30].replace("\n", " ")
        problems.append(f"unbound number {m.group(0)!r} in '...{ctx}...'")
    return problems


@unittest.skipUnless(_HAVE_GUIDE, _WHY)
class TheGuideIsInTheScientistsRegister(unittest.TestCase):
    def test_no_finding_ledger_or_date_ids(self):
        self.assertEqual(register_violations(_guide()), [],
                         "the scientist's guide carries audit-trail ids or dates; say what the "
                         "thing is instead and link the page that holds the id")

    def test_every_register_pattern_fires_on_a_mutation(self):
        clean = _guide()
        for token in ("A13", "V4", "S6-a", "I-" + "182", "D-" + "18", "2026-09-14", "09/06", "W4"):
            with self.subTest(token=token):
                mutated = clean.replace("## What it does", f"## What it does ({token})", 1)
                self.assertNotEqual(mutated, clean, "the mutation anchor is gone")
                self.assertTrue(register_violations(mutated), f"{token!r} was not caught")

    def test_the_names_with_digits_are_not_ids(self):
        """The allow-list for instrument and version names must not blind the id check."""
        self.assertEqual(register_violations("v3.1.4, v3.5, SODA-2, 2D-S, 2DC, 2DP, netCDF-4"),
                         [])


@unittest.skipUnless(_HAVE_GUIDE, _WHY)
class EveryNumberOnTheGuideIsBound(unittest.TestCase):
    def test_every_number_is_a_registry_value(self):
        self.assertEqual(number_problems(_guide()), [])

    def test_a_stale_bound_number_fails(self):
        want = _registry(("validation", "flights_validated_total"))
        mutated = _guide().replace(f"{want} field-campaign flights",
                                   f"{want + 1} field-campaign flights", 1)
        self.assertTrue(any("registry" in p for p in number_problems(mutated)))

    def test_an_unbound_number_fails(self):
        mutated = _guide().replace("## What it does", "## What it does\n\nIt is 42 % faster.", 1)
        self.assertTrue(any("unbound number '42'" in p for p in number_problems(mutated)))

    def test_a_reworded_binding_fails_rather_than_passing_silently(self):
        mutated = _guide().replace("of them exactly", "exactly", 1)
        self.assertTrue(number_problems(mutated))


# --------------------------------------------------------------------------
# 3. Mechanism claims, executed
# --------------------------------------------------------------------------

#: The sentence the guide carries while SODA-2's ASCII size-distribution export is unported.
SODA2_NOT_YET = "It does not yet write its size distributions to a file"


def soda2_claim_problem(text: str, ascii_export_ported: bool) -> str | None:
    if ascii_export_ported and SODA2_NOT_YET in text:
        return ("the SODA-2 driver now writes its ASCII size-distribution export "
                "(asciipsdfile is no longer refused), but the guide still says it writes no "
                "size-distribution file -- rewrite that paragraph to say what it writes and how "
                "to ask for it")
    if ascii_export_ported and "`asciipsdfile = 1`" not in text:
        return ("the SODA-2 driver writes its ASCII size-distribution export when "
                "asciipsdfile = 1, and the guide does not say how to ask for it")
    if not ascii_export_ported and SODA2_NOT_YET not in text:
        return (f"the SODA-2 driver still refuses its ASCII size-distribution export, so the "
                f"guide must say so ({SODA2_NOT_YET!r})")
    return None


def _soda2_ascii_export_is_ported() -> bool:
    """Ask the driver: a refusal by name before any file is read means not ported; reaching
    the raw-file read means the export is wired in."""
    from tests.test_soda2_process_2d import _base_op

    from arrayprobe_soda2.process_2d import soda2_process_2d
    missing = str(DATA / "__does_not_exist__.raw")
    try:
        soda2_process_2d(_base_op(fn=missing, asciipsdfile=1))
    except NotImplementedError as exc:
        if "asciipsdfile" in str(exc):
            return False
        raise
    except OSError:
        return True
    raise AssertionError("soda2_process_2d read a raw file that does not exist")


@unittest.skipUnless(_HAVE_GUIDE, _WHY)
class TheGuidesMechanismClaimsAreExecuted(unittest.TestCase):
    def test_the_default_engine_is_v35_and_the_other_is_v314(self):
        import uiops
        self.assertIn("`uiops.engine()` returns the v3.5 engine", _guide())
        self.assertEqual(uiops.engine().version, "3.5")
        self.assertEqual(uiops.engine("3.1.4").version, "3.1.4")

    def test_the_quoted_units_are_the_ones_both_engines_write(self):
        import netCDF4
        pairs = re.findall(r"`(\w+)` in `([^`]+)`", _guide())
        self.assertGreaterEqual(len(pairs), 4, "the units sentence was reworded; follow it")
        for name in ("demo_flight_v314_sd.nc", "demo_flight_v35_sd.nc"):
            with netCDF4.Dataset(DATA / name) as ds:
                for var, unit in pairs:
                    with self.subTest(file=name, var=var):
                        self.assertEqual(ds.variables[var].getncattr("units"), unit)
                self.assertNotIn("Conventions", ds.ncattrs())

    def test_the_bin_edges_share_the_quoted_unit(self):
        import netCDF4
        self.assertIn("`bin_min`, `bin_max` and `bin_mid` in `millimeter`", _guide())
        with netCDF4.Dataset(DATA / "demo_flight_v314_sd.nc") as ds:
            for var in ("bin_min", "bin_max", "bin_mid"):
                self.assertEqual(ds.variables[var].getncattr("units"), "millimeter")

    def test_the_quoted_file_formats_are_the_written_ones(self):
        import netCDF4
        text = _guide()
        # The guide names only the shipped engine's format; v3.1.4 is not in this package.
        self.assertIn("The v3.5 engine writes netCDF-4", text)
        with netCDF4.Dataset(DATA / "demo_flight_v35_sd.nc") as ds:
            self.assertEqual(ds.data_model, "NETCDF4")

    def test_the_flight_product_is_as_described(self):
        import netCDF4

        from arrayprobe.combine import combine_sizedist
        text = _guide()
        quoted = re.findall(r"`((?:Size Distribution|Number Concentration) cm-3|Time Vector)`",
                            text)
        self.assertGreaterEqual(len(quoted), 3)
        self.assertIn("The flight product carries no attributes at all", text)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "product.cdf"
            combine_sizedist([DATA / "demo_flight_v314_sd.nc"], out,
                             flight_date="20160101", summary_time="16_01_01_00_00_00")
            with netCDF4.Dataset(out) as ds:
                self.assertEqual(ds.ncattrs(), [])
                for name, var in ds.variables.items():
                    self.assertEqual(var.ncattrs(), [], f"{name} carries attributes")
                for name in quoted:
                    self.assertIn(name, ds.variables)

    @unittest.skipUnless(importlib.util.find_spec("arrayprobe_enhancements"),
                         "the enhancements package is not installed")
    def test_the_example_enhancement_runs_on_the_engine_the_example_names(self):
        from arrayprobe_enhancements import applicability, pipeline
        text = _guide()
        block = re.search(r"```toml\n\[enhancements\]\n(.*?)```", text, re.S)
        self.assertIsNotNone(block, "the guide's [enhancements] example is gone")
        names = re.findall(r"^(\w+)\s*=\s*true", block.group(1), re.M)
        self.assertTrue(names)
        command = re.search(r"`arrayprobe run --enhancements \S+ <raw files>(?: --engine (\S+))?`",
                            text)
        self.assertIsNotNone(command,
                             "the guide's arrayprobe run --enhancements command was reworded")
        # With no --engine on the command, the run takes the default engine the guide's
        # table names (v3.5); an explicit --engine on the command overrides it.
        self.assertIn("the **v3.5 engine**, the default", text)
        engine_name = command.group(1) or "3.5"
        for name in names:
            with self.subTest(enhancement=name):
                self.assertIn(name, pipeline._APPLIERS,
                              f"{name} has no driver adapter, so the example would not apply it")
                self.assertEqual(applicability.APPLICABILITY[name].state[engine_name],
                                 applicability.APPLIES)

    def test_the_soda2_paragraph_matches_the_driver(self):
        self.assertIsNone(soda2_claim_problem(_guide(), _soda2_ascii_export_is_ported()))

    def test_the_soda2_check_fires_in_both_directions(self):
        # Since the ASCII export merged (I1, 2026-09-15) the guide states what SODA-2 writes;
        # the check must still fire on a stale sentence, on a missing how-to, and on the
        # current text if the driver were to refuse the export again.
        text = _guide()
        stale = f"{text}\n{SODA2_NOT_YET}.\n"
        no_howto = text.replace("`asciipsdfile = 1`", "the export flag")
        for label, body, ported in (("stale sentence", stale, True),
                                    ("no how-to", no_howto, True),
                                    ("driver refuses", text, False)):
            with self.subTest(label):
                self.assertIsNotNone(soda2_claim_problem(body, ported))


# --------------------------------------------------------------------------
# 4. Placement
# --------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_GUIDE, _WHY)
class TheGuideIsWhereAReaderStarts(unittest.TestCase):
    def test_it_sorts_directly_after_the_index_and_the_index_links_it(self):
        spec = importlib.util.spec_from_file_location("docs_build_guide",
                                                      ROOT / "docs" / "_build" / "build.py")
        build = importlib.util.module_from_spec(spec)
        sys.modules.setdefault(spec.name, build)
        spec.loader.exec_module(build)
        slugs = [p["slug"] for p in build.read_pages()]
        self.assertEqual(slugs[:2], ["index", "scientists-guide"])
        # Pages link siblings by source name since 2026-10-02 (build.site_href rewrites
        # it to the built name), so the index names the guide's source file, and the
        # built index carries the rewritten href.
        self.assertIn("(00a-scientists-guide.md)", INDEX.read_text(encoding="utf-8"))
        self.assertEqual(build.site_href("00a-scientists-guide.md"), "scientists-guide.html")
        self.assertIn('href="scientists-guide.html"',
                      (ROOT / "docs" / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
