# SPDX-License-Identifier: BSD-3-Clause
"""Every file under ``tests/data/`` must account for where its values came from.

A fixture passes when either

* a ``tests/data/make_*.py`` script lists it in ``SYNTHETIC_OUTPUTS = (...)`` and reads no real or
  upstream data (none of :data:`FORBIDDEN_SOURCES` appears in its text), or
* it has a line in ``tests/data/FIXTURE_PROVENANCE.tsv``:
  ``<path relative to tests/data>\\t<one-line provenance reason>``.

Entries whose reason begins ``provenance unverified`` are known gaps, listed so
the guard passes while their origin is settled; they are not a clearance.
"""

import re
import shutil
import tempfile
import unittest
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
ALLOW_LIST = "FIXTURE_PROVENANCE.tsv"

FORBIDDEN_SOURCES = (
    "_upstream.source(",
    "ARRAYPROBE_REFERENCE_DATA",
    "old_oracles_data",
    "minimal_working_example",
)

#: Files that are not fixtures: the generators, notes, the allow-list itself, and the
#: ``*noShatters.mat`` workspace dumps sizeDist.m writes beside its output (gitignored,
#: never a test input), which exist in a checkout that ran the generator and not in a clone.
_NOT_FIXTURE = re.compile(
    r"(^|/)__pycache__/|\.py$|\.md$|noShatters\.mat$|^" + re.escape(ALLOW_LIST) + "$")


def _fixtures(root: Path) -> list[str]:
    out = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            if not _NOT_FIXTURE.search(rel):
                out.append(rel)
    return out


def _synthetic_names(root: Path) -> set[str]:
    """Basenames named by a make script that reads no real or upstream data."""
    names: set[str] = set()
    for script in sorted(root.glob("make_*.py")):
        text = script.read_text(encoding="utf-8", errors="replace")
        if any(s in text for s in FORBIDDEN_SOURCES):
            continue
        declared = re.search(r"^SYNTHETIC_OUTPUTS\s*=\s*\(([^)]*)\)", text, re.M)
        if declared:
            names.update(re.findall(r"[\"']([^\"'/\\]+)[\"']", declared.group(1)))
    return names


def excluded_fixture_names(rules: str) -> list[str]:
    """The single tests/data files the release allow-list carves out (globs left aside)."""
    out = []
    for line in rules.splitlines():
        m = re.match(r"!tests/data/([^/\t*]+)\t", line)
        if m:
            out.append(m.group(1))
    return out


def _allow_list(root: Path) -> dict[str, str]:
    path = root / ALLOW_LIST
    entries: dict[str, str] = {}
    if not path.exists():
        return entries
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        name, sep, reason = line.partition("\t")
        if not sep or not reason.strip():
            raise ValueError(f"{ALLOW_LIST}:{n}: needs '<path>\\t<reason>': {line!r}")
        entries[name.strip()] = reason.strip()
    return entries


def unaccounted(root: Path) -> list[str]:
    """Fixtures with neither a synthetic make script nor an allow-list entry."""
    synthetic = _synthetic_names(root)
    allowed = _allow_list(root)
    return [
        rel for rel in _fixtures(root)
        if rel not in allowed and rel.rsplit("/", 1)[-1] not in synthetic
    ]


def real_data_present(root: Path) -> list[str]:
    """Present fixtures whose allow-list reason classifies them REAL-DATA.

    Listing a real-data file is not a clearance: it must be excluded from the
    release (``# EXCLUDED`` row, file removed, dependent tests skip).
    """
    present = set(_fixtures(root))
    return sorted(
        name for name, reason in _allow_list(root).items()
        if reason.upper().startswith("REAL-DATA") and name in present
    )


class TestReleaseFixturesAreSynthetic(unittest.TestCase):
    def test_no_present_fixture_is_real_data(self):
        found = real_data_present(DATA)
        self.assertEqual(
            found, [],
            f"real-data fixtures are not shipped: remove each, mark its {ALLOW_LIST} row "
            "'# EXCLUDED', and make its dependent tests skip",
        )

    def test_every_fixture_is_synthetic_or_listed(self):
        missing = unaccounted(DATA)
        self.assertEqual(
            missing, [],
            f"add a synthetic make_*.py for each, or a line to tests/data/{ALLOW_LIST}",
        )

    def test_allow_list_names_only_existing_files(self):
        present = set(_fixtures(DATA))
        listed = _allow_list(DATA)
        # A row tagged NOT-SHIPPED names a file the release builder leaves out, so it is absent
        # from the public tree and present in the development one; both are correct.
        stale = sorted(n for n in set(listed) - present if "NOT-SHIPPED" not in listed[n])
        self.assertEqual(stale, [], f"{ALLOW_LIST} lists files that are not in tests/data")

    def test_every_excluded_fixture_row_says_not_shipped(self):
        # Three rows lost this tag when their carve-outs were added (2026-10-30), and only the
        # public tree's run of the test above noticed. The allow-list ships with neither tree's
        # builder in the public one, so this check runs where the builder's list exists.
        rules = DATA.parent.parent / "scripts" / "release_allowlist.txt"
        if not rules.is_file():
            self.skipTest("no release allow-list here (a built release tree)")
        listed = _allow_list(DATA)
        untagged = sorted(n for n in excluded_fixture_names(rules.read_text(encoding="utf-8"))
                          if n in listed and "NOT-SHIPPED" not in listed[n])
        self.assertEqual(untagged, [], f"tag these {ALLOW_LIST} rows NOT-SHIPPED")

    def test_the_not_shipped_check_fires(self):
        rules = "!tests/data/x.json\treason\n!tests/data/sub/**\treason\n"
        self.assertEqual(excluded_fixture_names(rules), ["x.json"])

    def test_header_fixture_is_written_by_the_synthetic_generator(self):
        self.assertIn("2DS_header_fixture.nc", _synthetic_names(DATA))
        self.assertNotIn("2DS_header_fixture.nc", _allow_list(DATA))


class TestTheGuardFires(unittest.TestCase):
    """The check is exercised on a copy, so a guard that matches nothing fails here."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        shutil.copy(DATA / ALLOW_LIST, self.root / ALLOW_LIST)

    def tearDown(self):
        self._tmp.cleanup()

    def test_an_unlisted_file_is_reported(self):
        (self.root / "unlisted_real_cut.nc").write_bytes(b"CDF\x01")
        self.assertEqual(unaccounted(self.root), ["unlisted_real_cut.nc"])

    def test_a_make_script_reading_upstream_data_does_not_clear_its_output(self):
        (self.root / "cut.nc").write_bytes(b"CDF\x01")
        (self.root / "make_cut.py").write_text(
            'SOURCE = _upstream.source("uiops314")\nSYNTHETIC_OUTPUTS = ("cut.nc",)\n',
            encoding="utf-8",
        )
        self.assertEqual(unaccounted(self.root), ["cut.nc"])

    def test_a_synthetic_make_script_clears_its_output(self):
        (self.root / "made_up.nc").write_bytes(b"CDF\x01")
        (self.root / "make_made_up.py").write_text(
            'SYNTHETIC_OUTPUTS = ("made_up.nc",)\n', encoding="utf-8")
        self.assertEqual(unaccounted(self.root), [])

    def test_a_present_real_data_fixture_is_reported(self):
        (self.root / "real_cut.nc").write_bytes(b"CDF\x01")
        with open(self.root / ALLOW_LIST, "a", encoding="utf-8") as fh:
            fh.write("\nreal_cut.nc\tREAL-DATA: slice of a real flight file\n")
        self.assertEqual(real_data_present(self.root), ["real_cut.nc"])

    def test_an_excluded_real_data_row_without_its_file_passes(self):
        with open(self.root / ALLOW_LIST, "a", encoding="utf-8") as fh:
            fh.write("\n# EXCLUDED gone.nc\tEXCLUDED from the release\n")
        self.assertNotIn("gone.nc", real_data_present(self.root))

    def test_an_entry_without_a_reason_is_refused(self):
        (self.root / ALLOW_LIST).write_text("some_file.nc\t\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            _allow_list(self.root)


if __name__ == "__main__":
    unittest.main()
