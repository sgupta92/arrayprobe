# SPDX-License-Identifier: BSD-3-Clause
"""``examples/ORDER.toml`` is the designed notebook order, and the notebooks must match it.

The design
renumbers the 30 notebooks along a new user's path, but the renaming is deferred to the
pre-release check. Until then this module guards the two halves separately:

* **(a) The registry and the directory agree** (passes today): every ``examples/*.ipynb``
  appears in ``ORDER.toml`` by its current filename (``old``), and every ``old`` names a
  file that exists. A notebook added without an entry, or removed without one, fails here.
* **(b) The numbers match the design** (``expectedFailure`` until the pre-release check):
  each file's numeric prefix equals its designed ``number`` and its name equals ``name``.
  It turns green when the renaming lands; remove the decorator then, and the unexpected
  success reminds whoever forgets.

The two sides come from different places: the registry is written by hand from the design,
the file list from the directory. ``TestAgreementCheckFires`` runs the same check on a
synthetic directory so a check that matches nothing cannot pass silently.
"""

from __future__ import annotations

import re
import tempfile
import tomllib
import unittest
from pathlib import Path

from tests._hygiene import hygiene
from tests._repo import repo_only

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
ORDER = EXAMPLES / "ORDER.toml"
#: Present in the development repository, absent from a release tree.
ALLOWLIST = ROOT / "scripts" / "release_allowlist.txt"


def load_order(path: Path = ORDER) -> list[dict]:
    with path.open("rb") as fh:
        return tomllib.load(fh)["notebook"]


def release_excluded(allowlist: Path = ALLOWLIST) -> set[str]:
    """Notebooks the release allow-list excludes by exact path, relative to ``examples/``.

    Empty where the allow-list is absent (a release tree), so there every notebook on disk
    must be listed."""
    if not allowlist.is_file():
        return set()
    prefix = "!examples/"
    return {line.split("	", 1)[0].strip()[len(prefix):]
            for line in allowlist.read_text(encoding="utf-8").splitlines()
            if line.startswith(prefix) and line.split("	", 1)[0].strip().endswith(".ipynb")}


def disagreements(order: list[dict], directory: Path,
                  excluded: set[str] = frozenset()) -> list[str]:
    """Differences between the registry's ``old`` names and the notebooks in ``directory``.

    A notebook in ``excluded`` may be on disk unlisted (it does not ship); it may not be listed."""
    on_disk = {p.relative_to(directory).as_posix() for p in directory.rglob("*.ipynb")
               if ".ipynb_checkpoints" not in p.parts} - set(excluded)
    listed = [e["old"] for e in order]
    problems = [f"on disk, not in ORDER.toml: {n}" for n in sorted(on_disk - set(listed))]
    problems += [f"in ORDER.toml, not on disk: {n}" for n in sorted(set(listed) - on_disk)]
    problems += [f"listed twice: {n}" for n in sorted({n for n in listed if listed.count(n) > 1})]
    return problems


def numbering_problems(order: list[dict], directory: Path) -> list[str]:
    """Files whose current prefix is not the designed number (names must also match)."""
    problems = []
    for e in order:
        m = re.match(r"(\d+)_", e["old"])
        have = int(m.group(1)) if m else None
        if have != e["number"] or e["old"] != e["name"]:
            problems.append(f"{e['old']}: prefix {have}, designed {e['number']:02d} ({e['name']})")
    return problems


@hygiene
@repo_only
class TestOrderRegistry(unittest.TestCase):
    def test_registry_is_well_formed(self):
        order = load_order()
        self.assertEqual(list(range(len(order))), [e["number"] for e in order])
        for e in order:
            # A track folder, then the notebook's position within that track.
            self.assertRegex(e["name"], r"^[1-7]_[a-z0-9_]+/\d{2}_[a-z0-9_]+\.ipynb$")
            self.assertEqual(e["track"], e["name"].split("/")[0])

    def test_a_every_notebook_is_listed_and_every_entry_exists(self):
        self.assertEqual([], disagreements(load_order(), EXAMPLES, release_excluded()))

    def test_an_excluded_notebook_may_not_be_listed(self):
        """The exemption covers a notebook left unlisted, never one the registry still names."""
        order = [{"old": "x/01_kept.ipynb"}, {"old": "x/02_gone.ipynb"}]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "x").mkdir()
            for name in ("01_kept", "02_gone"):
                (Path(tmp) / "x" / f"{name}.ipynb").write_text("{}", encoding="utf-8")
            self.assertEqual(["in ORDER.toml, not on disk: x/02_gone.ipynb"],
                             disagreements(order, Path(tmp), {"x/02_gone.ipynb"}))
            self.assertEqual([], disagreements(order[:1], Path(tmp), {"x/02_gone.ipynb"}))

    @unittest.expectedFailure
    def test_b_numeric_prefixes_match_the_designed_numbers(self):
        """Turns green at the pre-release check, when the renumbering lands.

        Remove ``expectedFailure`` in the commit that performs the ``git mv`` list in the
        design's section 3; until then 25 of 30 prefixes differ by design.
        """
        self.assertEqual([], numbering_problems(load_order(), EXAMPLES))


@hygiene
class TestAgreementCheckFires(unittest.TestCase):
    def test_check_a_fires_on_a_synthetic_directory(self):
        order = [
            {"number": 0, "name": "00_a.ipynb", "old": "00_a.ipynb"},
            {"number": 1, "name": "01_b.ipynb", "old": "02_b.ipynb"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "00_a.ipynb").write_text("{}")
            (d / "extra.ipynb").write_text("{}")
            problems = disagreements(order, d)
        self.assertIn("on disk, not in ORDER.toml: extra.ipynb", problems)
        self.assertIn("in ORDER.toml, not on disk: 02_b.ipynb", problems)

    def test_check_b_fires_when_a_prefix_differs(self):
        order = [{"number": 3, "name": "03_x.ipynb", "old": "04_x.ipynb"}]
        self.assertEqual(1, len(numbering_problems(order, Path("."))))


if __name__ == "__main__":
    unittest.main()
