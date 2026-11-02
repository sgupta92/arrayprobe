# SPDX-License-Identifier: BSD-3-Clause
"""Every dependency group is declared twice, and the two declarations must agree.

WHY THIS TEST EXISTS. This package states its dependencies in two places with two
different jobs. ``requirements*.txt`` pins exact versions and is what this repository, CI
and the author's laptop install. ``pyproject.toml`` declares ranges and is what a
**stranger** installs. Nothing connected them, and on 2026-09-09 -- while running the
minimum-versions check -- they were found to
disagree in **seven** places across two groups:

===========================  ==============  =========================================
requirements file            metadata group  pinned, but the metadata never mentions it
===========================  ==============  =========================================
``requirements.txt``         dependencies    -- none --
``requirements-extra.txt``   ``extra``       numba
``requirements-dev.txt``     ``dev``         build, coverage, pre-commit, pypdf,
                                             reportlab, twine
===========================  ==============  =========================================

**Two of them break the suite for whoever installs by the metadata**, and they break it
in the two different ways this project keeps meeting:

* **reportlab and pypdf** are imported by the paper tests. Installing ``arrayprobe[dev]``
  and running the suite gave **4 errors** -- loud, at least. Both are now declared.
* **numba** is guarded ``skipUnless(reject.HAVE_NUMBA)``. Installing ``arrayprobe[extra]``
  makes nine kernel-equivalence tests **skip**, and the suite reports OK having never
  checked that the JIT kernels compute what the pure-Python bodies compute. That is the
  silent variety -- the same shape as the sdist that shipped 130 test modules and none of
  their fixtures.

WHAT THIS TEST DOES NOT DECIDE. Whether a package *belongs* in the metadata is sometimes a
real trade-off rather than an oversight -- numba constrains numpy from **above**, so
declaring it makes ``[extra]`` a resolution that can fail on a numpy the core supports,
which is exactly the breakage item 5 documented for ``scipy>=1.11``. So this test does not
force the fix. It forces the divergence to be **declared**, in
:data:`DELIBERATELY_UNDECLARED`, with a reason. Silence is what it refuses.

The two sides come from different files in different formats, which is the property this
project requires of a check -- "a check must draw its two sides from different places, or
it is testing nothing".

No TOML parser: ``dependencies`` is a block and the extras are one line each, all of fixed
shape, and the rest of this repository reads such things with a regular expression rather
than adding an import to a test. The parsers are asserted to find something before
anything is concluded from what they report -- four guards in this repository were found
matching nothing while reading perfectly well.
"""

from __future__ import annotations

import importlib.metadata
import re
import unittest
from pathlib import Path

from tests._pins import requirements_files_present
from tests._repo import repo_only

# python_port root -- and the sdist root when unpacked from the tarball.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

#: ``(requirements file, metadata group)`` -- every pair that must agree.
PAIRS: tuple[tuple[str, str], ...] = (
    ("requirements.txt", "dependencies"),
    ("requirements-extra.txt", "extra"),
    ("requirements-dev.txt", "dev"),
)

#: ``(group, distribution) -> why``. A package pinned in a requirements file and
#: deliberately absent from the matching metadata group. Adding an entry records a
#: decision; it does not silence a finding. An empty or throwaway reason fails below,
#: and an entry whose package is no longer pinned fails too -- an allowlist that
#: outlives its subject is how a guard goes quiet.
DELIBERATELY_UNDECLARED: dict[tuple[str, str], str] = {
    ("extra", "zarr"): (
        "Declared in its own [zarr] extra (2026-10-08), not in [extra]: "
        "the Zarr writer is opt-in and netCDF4 is the default output, so "
        "`pip install arrayprobe[extra]` should not pull zarr, xarray and pandas "
        "for a feature most users never call. Pinned here so the development "
        "venv and CI exercise export_zarr."),
    ("extra", "xarray"): (
        "Declared in its own [zarr] extra (2026-10-08), not in [extra]: "
        "the Zarr writer is opt-in and netCDF4 is the default output, so "
        "`pip install arrayprobe[extra]` should not pull zarr, xarray and pandas "
        "for a feature most users never call. Pinned here so the development "
        "venv and CI exercise export_zarr."),
    ("extra", "pyarrow"): (
        "Declared in its own [parquet] extra (2026-10-13), not in [extra]: "
        "the Parquet writer is opt-in and netCDF4 is the default output, so "
        "`pip install arrayprobe[extra]` should not pull pyarrow for a feature most "
        "users never call. Pinned here so the development venv and CI exercise "
        "export_parquet."),
    ("extra", "numba"): (
        "STILL THE AUTHOR'S CALL, but the arithmetic it rests on is now measured rather "
        "than assumed (2026-09-11). The concern was that numba pins numpy from ABOVE, so "
        "declaring it in [extra] could make that extra unresolvable on a numpy the core "
        "supports -- the shape of scipy>=1.11, which named a configuration pip could not "
        "install (PACKAGE_HARDENING item 5). THE PRODUCT IS NOT EMPTY TODAY: numba 0.67.0 "
        "requires numpy<2.6,>=1.22 and the core requires numpy>=2.0, so any numpy in "
        "[2.0, 2.6) satisfies both, and 2.5.2 is what is installed. The hazard is "
        "PROSPECTIVE -- it bites the day numpy 2.6 ships while numba's ceiling stands, at "
        "which point `arrayprobe[extra]` could not be installed at the newest numpy the "
        "core permits. `NumbaAndTheCoreNumpyStillOverlap` below fails on that day instead "
        "of leaving it to be discovered by a stranger's pip. Measured consequence of "
        "leaving numba undeclared, unchanged: `pip install arrayprobe[extra]` gives "
        "HAVE_NUMBA False and the 9 kernel-equivalence tests in "
        "test_reject_numba_equivalence.py SKIP rather than run, so a stranger's suite "
        "reports OK without ever checking the compiled path."
    ),
    # build, coverage, pre-commit and twine were allowlisted here as command-only tooling
    # until 2026-10-05, when the dependency sweep declared them in [dev] so the
    # metadata matches requirements-dev.txt.
}

class NumbaAndTheCoreNumpyStillOverlap(unittest.TestCase):
    """The prospective half of the numba-extra decision, as a check.

    Leaving `numba` out of `[extra]` is the author's call and this does not
    touch it. What it does is stop the reason for that call from being a
    guess. The reason is that numba bounds numpy from above while this
    package's core bounds it from below, and two such bounds can describe an
    empty set -- which is exactly how `scipy>=1.11` came to name a
    configuration pip could not install.

    Measured 2026-09-11: numba 0.67.0 wants ``numpy<2.6,>=1.22``, the core
    wants ``numpy>=2.0``, so the product is ``[2.0, 2.6)`` and non-empty. The
    day that stops being true -- numpy 2.6 with numba's ceiling unmoved -- this
    fails, rather than a stranger's `pip install arrayprobe[extra]` discovering
    it. Two sides from different places: the ceiling comes from the installed
    numba's own metadata, the floor from `pyproject.toml`.

    Skips, rather than failing, where numba is absent: it is an optional
    extra, and a core-only environment has nothing to check.
    """

    def setUp(self):
        try:
            self.numba_requires = importlib.metadata.requires("numba") or []
        except importlib.metadata.PackageNotFoundError:
            self.skipTest("numba is not installed; nothing to compare")

    def _numba_numpy_ceiling(self) -> str | None:
        for requirement in self.numba_requires:
            if not requirement.lower().startswith("numpy"):
                continue
            for clause in requirement.split(";")[0].split(","):
                clause = clause.strip()
                if clause.startswith("numpy<") or clause.startswith("<"):
                    return clause.removeprefix("numpy").strip()
        return None

    def _core_numpy_floor(self) -> str | None:
        text = _PYPROJECT.read_text(encoding="utf-8")
        match = re.search(r'"numpy(>=[0-9][^"]*)"', text)
        return match.group(1) if match else None

    def test_the_parsers_find_something_before_anything_is_concluded(self):
        """Four guards in this repository were found matching nothing while
        reading perfectly well; this file's own docstring says so."""
        self.assertIsNotNone(self._numba_numpy_ceiling(),
                             f"no numpy upper bound found in numba's metadata: "
                             f"{self.numba_requires}")
        self.assertIsNotNone(self._core_numpy_floor(),
                             "no numpy floor found in pyproject.toml's core deps")

    @staticmethod
    def _release(version: str) -> tuple[int, ...]:
        """The numeric release tuple of a version string.

        A local three-line parser rather than `packaging.version`: nothing in
        this package declares `packaging`, and importing it here -- in the very
        file that exists to catch undeclared imports -- would be the joke
        writing itself. Only the release segment is compared, which is all
        these bounds ever carry.
        """
        head = re.match(r"\d+(?:\.\d+)*", version.strip())
        return tuple(int(part) for part in head.group(0).split(".")) if head else ()

    def test_the_installed_numpy_satisfies_both_bounds(self):
        """The product is non-empty, demonstrated by a member of it.

        Checked against the numpy actually installed rather than by reasoning
        about strings: a resolver's answer is what matters, and this
        environment is one.
        """
        ceiling = self._numba_numpy_ceiling()
        floor = self._core_numpy_floor()
        if ceiling is None or floor is None:
            self.skipTest("bounds not parseable; the guard above reports that")
        installed = self._release(importlib.metadata.version("numpy"))
        upper = self._release(ceiling.lstrip("<="))
        lower = self._release(floor.lstrip(">="))
        self.assertLess(
            lower, upper,
            f"the core's numpy floor ({floor}) has caught up with numba's "
            f"ceiling ({ceiling}): declaring numba in [extra] would now name a "
            "configuration pip cannot install, and leaving it out no longer "
            "costs only the skipped kernel tests. Revisit the exemption in "
            "DELIBERATELY_UNDECLARED.")
        self.assertTrue(
            lower <= installed < upper,
            f"the installed numpy {installed} is outside [{lower}, {upper}); "
            "this environment cannot demonstrate the product is inhabited")


_PIN = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*(?:[=<>!~]=|[<>])")


def _pinned(path: Path) -> set[str]:
    """Distribution names pinned in a requirements file, ignoring ``-r`` includes."""
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = _PIN.match(line)
        if m:
            names.add(m.group(1).lower())
    return names


def _declared(path: Path, group: str) -> set[str]:
    """Distribution names in ``dependencies = [...]`` (a block) or an extras line."""
    text = path.read_text(encoding="utf-8")
    if group == "dependencies":
        block = re.search(r"^dependencies = \[(.*?)^\]", text, re.S | re.M)
        source = block.group(1) if block else ""
    else:
        lines = [ln for ln in text.splitlines() if ln.strip().startswith(f"{group} = [")]
        source = lines[0] if lines else ""
    return {m.group(1).lower()
            for m in re.finditer(r'"([A-Za-z0-9_.\-]+)\s*[=<>!~]', source)}


@unittest.skipUnless(
    requirements_files_present(),
    "the requirements files are development pins and do not ship; pyproject.toml's "
    "[pinned] extra carries them in the public tree",
)
class TheDeclarationsAgree(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(_PYPROJECT.is_file(), f"missing {_PYPROJECT}")
        self.core = _pinned(_REPO_ROOT / "requirements.txt")

    def test_every_requirements_file_exists(self) -> None:
        for fname, _ in PAIRS:
            with self.subTest(fname=fname):
                self.assertTrue((_REPO_ROOT / fname).is_file())

    def test_the_parsers_find_something(self) -> None:
        """Assert the readers work before trusting what they report.

        Every guard this project has found inert read its input correctly and matched
        nothing. A parser that silently returns an empty set would make every assertion
        below pass by vacuity.
        """
        self.assertIn("numpy", self.core)
        self.assertIn("numpy", _declared(_PYPROJECT, "dependencies"))
        self.assertIn("scipy", _declared(_PYPROJECT, "extra"))
        self.assertIn("pytest", _declared(_PYPROJECT, "dev"))
        self.assertIn("reportlab", _pinned(_REPO_ROOT / "requirements-dev.txt"))

    def test_nothing_is_pinned_without_being_declared_or_explained(self) -> None:
        problems: dict[str, list[str]] = {}
        for fname, group in PAIRS:
            pinned = _pinned(_REPO_ROOT / fname)
            declared = _declared(_PYPROJECT, group)
            # requirements-extra/dev start `-r requirements.txt`, so the core pins are
            # already covered by `dependencies` and are not this group's business.
            base = set() if group == "dependencies" else self.core
            missing = sorted(
                p for p in pinned - declared - base
                if (group, p) not in DELIBERATELY_UNDECLARED)
            if missing:
                problems[f"{fname} -> {group}"] = missing
        self.assertEqual(
            problems, {},
            f"pinned in a requirements file, absent from the matching metadata group, and "
            f"not recorded as deliberate: {problems}. Either declare them -- so a metadata "
            f"install matches what this repository actually tests -- or add "
            f"(group, name) to DELIBERATELY_UNDECLARED with the reason and the measured "
            f"consequence.")

    def test_nothing_is_declared_that_is_pinned_nowhere(self) -> None:
        """The other direction: metadata offering something no run has ever installed."""
        problems: dict[str, list[str]] = {}
        for fname, group in PAIRS:
            spare = sorted(_declared(_PYPROJECT, group)
                           - _pinned(_REPO_ROOT / fname))
            if spare:
                problems[f"{group} -> {fname}"] = spare
        self.assertEqual(
            problems, {},
            f"declared in pyproject.toml but pinned in no requirements file, so no run of "
            f"this repository has ever installed it: {problems}")

    def test_recorded_divergences_carry_a_real_reason(self) -> None:
        for key, reason in DELIBERATELY_UNDECLARED.items():
            with self.subTest(key=key):
                self.assertGreater(
                    len(reason), 80,
                    f"{key} is recorded as deliberate with no usable reason. The allowlist "
                    f"exists to hold the decision, not to hide it.")

    def test_the_allowlist_is_not_stale(self) -> None:
        by_group = {g: _pinned(_REPO_ROOT / f) for f, g in PAIRS}
        stale = sorted(f"{g}:{n}" for (g, n) in DELIBERATELY_UNDECLARED
                       if n not in by_group.get(g, set()))
        self.assertEqual(
            stale, [],
            f"DELIBERATELY_UNDECLARED names packages the requirements files no longer pin: "
            f"{stale}. Remove the entries.")

    def test_the_two_packages_the_suite_actually_imports_are_declared(self) -> None:
        """reportlab and pypdf specifically -- this is what the floors run caught.

        Named rather than left to the general rule, because the general rule can be
        satisfied by an allowlist entry, and these two must never be satisfied that way:
        without them ``pip install arrayprobe[dev]`` yields a suite that errors.
        """
        dev = _declared(_PYPROJECT, "dev")
        for name in ("reportlab", "pypdf"):
            with self.subTest(name=name):
                self.assertIn(
                    name, dev,
                    f"{name} is imported by the test suite; `pip install arrayprobe[dev]` "
                    f"must be able to run that suite.")


@repo_only
class TheNetCDF4FloorHasWheelsEverywhere(unittest.TestCase):
    """netCDF4 1.7.0 and 1.7.1 publish no cp313 wheel. Under Python 3.13 a resolve
    that lands on them (a lowest-bounds resolve, an offline mirror) builds from the
    sdist and dies with 'did not find netCDF version 4 headers' -- naming neither the
    Python nor the floor. Measured in the fresh-install matrix of 2026-09-26; 1.7.2
    is the first release with wheels on every Python this package supports. The
    two enhancement packages declare the same library and are held to the same
    floor; they are absent from an unpacked sdist, which is not a failure."""

    FLOOR = (1, 7, 2)

    def test_every_declared_netcdf4_floor_is_at_least_1_7_2(self) -> None:
        pyprojects = [_PYPROJECT,
                      _REPO_ROOT / "enhancements_uiops" / "pyproject.toml",
                      _REPO_ROOT / "enhancements_soda2" / "pyproject.toml"]
        checked = 0
        for path in pyprojects:
            if not path.is_file():
                continue
            floors = re.findall(r'"netCDF4>=([0-9.]+)"', path.read_text(encoding="utf-8"))
            with self.subTest(pyproject=str(path)):
                self.assertEqual(len(floors), 1, f"expected one netCDF4 floor in {path}")
                floor = tuple(int(p) for p in floors[0].split("."))
                self.assertGreaterEqual(floor, self.FLOOR)
            checked += 1
        self.assertGreaterEqual(checked, 1, "no pyproject.toml was read")


if __name__ == "__main__":
    unittest.main()
