# SPDX-License-Identifier: BSD-3-Clause
"""Decision #9 (2026-08-28): each installable package ships a LICENSE, byte-identical to the
repo-root licence (BSD-3-Clause since 2026-10-09). The root file is the master; the copies
exist for packaging.

**WIDENED 2026-09-21 (packaging finalisation pass).** This named two paths --
``python_port`` and ``enhancements`` -- and there are three installable
distributions. ``enhancements_soda2`` became one when
``arrayprobe-soda2-enhancements`` was split out, shipped a ``LICENSE`` from that
day, and was checked by nothing: the file it ships could have been empty, a BSD
text, or the wrong GPL version, and this test would still have passed while
claiming in its own docstring to cover "each installable package".

That is the failure family this repository keeps finding -- a check that names
instances where it should derive the class -- so the list is now **derived from
the distributions themselves**: every ``pyproject.toml`` carrying a
``[project]`` name, excluding worktrees and virtual environments. A fourth
distribution is covered the day it exists, without anybody remembering to add a
line here.

Line endings are deliberately not normalised away before comparing. The
comparison is on bytes because ``LICENSE`` carries no ``.gitattributes`` rule
and the repository's ``core.autocrlf`` decides the working copy's form for all
four together; a copy that disagrees with the master in this working tree is a
copy some tool wrote rather than git, which is exactly what a byte comparison
should surface.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Directories a `pyproject.toml` can sit in without being a distribution of
#: this repository's own: agent worktrees are whole copies of the tree, and a
#: venv can vendor a build backend's own project file.
_NOT_OURS = (".claude", ".venv", "site-packages", "_upstream", "node_modules")


def _distribution_roots() -> list[Path]:
    """Every directory holding a `pyproject.toml` that declares a `[project]` name.

    Two sides from different places: this side is the filesystem's own answer to
    "what does this repository build", not a list typed into a test.

    **One level deep, not `rglob`.** An `rglob("pyproject.toml")` from the
    repository root took 78 s here -- it walks the agent worktrees, the
    gitignored reference-data tree and every venv before discarding them -- and
    a check that costs more than a minute gets gated out of the default run,
    which is how a guard stops being executed. Every distribution this
    repository builds sits directly under the root, so that is where it looks.
    """
    roots = []
    for directory in sorted([ROOT, *(p for p in ROOT.iterdir() if p.is_dir())]):
        if directory.name in _NOT_OURS:
            continue
        pyproject = directory / "pyproject.toml"
        if not pyproject.is_file():
            continue
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        if "\nname = " in text or text.startswith("name = "):
            roots.append(directory)
    return roots


#: The attribution documents that must travel with every distribution, each a
#: single master at the repository root with a per-distribution copy beside it.
#:
#: Added 2026-09-21 (packaging finalisation, §3.4). Both files lived only at the
#: repository root, which is ABOVE every project root, and setuptools >= 84
#: refuses to reach up -- so they travelled in none of the three sdists and none
#: of the three wheels. A recipient got ``LICENSE`` and the per-module UCAR
#: docstrings and no statement of whose work this reproduces or how to cite it.
#: The remedy is the one ``LICENSE`` already uses: copy, and let a test rather
#: than a habit hold the copies to the master.
#:
#: Each name here must also be named by every distribution's ``MANIFEST.in``:
#: that is what puts a root-level file which is neither a licence nor the
#: declared ``readme`` into a source distribution. NOTICE.md additionally
#: reaches the *wheel* for free -- setuptools' default ``license-files`` globs
#: include ``NOTICE*`` -- but that is a second route, not a reason to leave it
#: out of the manifest.
_ATTRIBUTION_MASTERS = ("NOTICE.md", "CITATION.cff")


_APACHE_HEADING = b"## Full text: Apache License 2.0"


def _ships_apache(root: Path) -> bool:
    """True where the distribution contains an Apache-licensed source file or
    declares the Apache text (the root and enhancements_uiops, via field2006_shatter)."""
    if (root / "LICENSES" / "Apache-2.0.txt").is_file():
        return True
    for py in root.rglob("*.py"):
        if "Apache-2.0" in py.read_text(encoding="utf-8", errors="replace")[:600]:
            return True
    return False


def _without_apache_text(master: bytes) -> bytes:
    """The root NOTICE.md up to its Apache full-text section, which is the last."""
    i = master.index(_APACHE_HEADING)
    return master[:i].rstrip(b"\n") + b"\n"


class LicenseCopies(unittest.TestCase):
    def setUp(self) -> None:
        self.master = (ROOT / "LICENSE").read_bytes()
        self.assertIn(b"BSD 3-Clause License", self.master)
        self.roots = _distribution_roots()

    def test_the_distribution_list_is_not_empty(self):
        """The derivation must produce something, or the sweep below tests nothing."""
        self.assertGreaterEqual(
            len(self.roots), 3,
            f"only {len(self.roots)} distribution(s) found under {ROOT}; this repository "
            "builds at least three (python_port, enhancements, enhancements_soda2). The "
            "derivation broke, so the sweep below would pass vacuously.")

    def test_every_distribution_ships_the_master_licence(self):
        for root in self.roots:
            with self.subTest(distribution=root.name):
                copy = root / "LICENSE"
                self.assertTrue(
                    copy.is_file(),
                    f"{root.name} is an installable distribution and ships no LICENSE. "
                    "The licence travels with every redistribution; a wheel without it is not "
                    "one this project can publish.")
                self.assertEqual(
                    copy.read_bytes(), self.master,
                    f"{copy} drifted from the root LICENSE (master is {len(self.master)} "
                    f"bytes, this copy is {copy.stat().st_size})")


class AttributionCopies(unittest.TestCase):
    """`NOTICE.md` and `CITATION.cff` travel, and the copies do not drift.

    Before 2026-09-21 they travelled in **none** of the three distributions:
    both live at the repository root, above every project root, and setuptools
    >= 84 refuses a source file above the project root. A recipient of any
    tarball or wheel got `LICENSE` and the per-module UCAR docstrings, and no
    statement of whose work this reproduces or how to cite it.

    Two sides from different places: the master's bytes at the repository root,
    and each distribution's own copy plus its `MANIFEST.in` text.
    """

    def setUp(self) -> None:
        self.roots = _distribution_roots()
        self.assertGreaterEqual(len(self.roots), 3, "the derivation broke")

    def test_every_distribution_carries_every_attribution_master(self):
        for name in _ATTRIBUTION_MASTERS:
            master = (ROOT / name).read_bytes()
            self.assertTrue(master, f"{name} at the repository root is empty")
            for root in self.roots:
                with self.subTest(distribution=root.name, file=name):
                    copy = root / name
                    if name == "NOTICE.md" and not _ships_apache(root):
                        expected = _without_apache_text(master)
                    else:
                        expected = master
                    self.assertTrue(
                        copy.is_file(),
                        f"{root.name} is an installable distribution and ships no "
                        f"{name}. Copy the repository-root master into it: the "
                        "attribution document and the citation file are the two things "
                        "a recipient cannot reconstruct.")
                    self.assertEqual(
                        copy.read_bytes(), expected,
                        f"{copy} drifted from the root {name} (master is "
                        f"{len(master)} bytes, this copy is {copy.stat().st_size}). "
                        f"The root file is the master; refresh the copy from it.")

    def test_apache_text_only_where_an_apache_module_ships(self):
        """A distribution's NOTICE.md carries the Apache full text if and only if
        an Apache-licensed file is in it (only field2006_shatter.py is)."""
        for root in self.roots:
            with self.subTest(distribution=root.name):
                notice = (root / "NOTICE.md").read_bytes()
                self.assertEqual(
                    _APACHE_HEADING in notice, _ships_apache(root),
                    f"{root.name}/NOTICE.md and its contents disagree about Apache-2.0")
        soda2 = ROOT / "enhancements_soda2"
        self.assertFalse(_ships_apache(soda2), "enhancements_soda2 now holds Apache code")
        self.assertNotIn(b"Apache License", (soda2 / "NOTICE.md").read_bytes()
                         .split(b"## Full text: BSD-3-Clause")[-1].split(b"\n```\n", 2)[-1])

    def test_every_manifest_ships_them(self):
        """A copy nobody packages is a copy that still does not travel."""
        for root in self.roots:
            manifest = root / "MANIFEST.in"
            with self.subTest(distribution=root.name):
                self.assertTrue(
                    manifest.is_file(),
                    f"{root.name} has no MANIFEST.in, so nothing root-level travels "
                    "in its sdist beyond what setuptools includes by default.")
                text = manifest.read_text(encoding="utf-8")
                for name in _ATTRIBUTION_MASTERS:
                    self.assertIn(
                        f"include {name}", text,
                        f"{manifest} does not name {name}, so the copy beside it does "
                        "not reach the source distribution.")


if __name__ == "__main__":
    unittest.main()


#: SHA-256 of the Apache License 2.0 text as apache.org serves it
#: (https://www.apache.org/licenses/LICENSE-2.0.txt, fetched 2026-10-09).
_APACHE_2_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"


#: The heading in the root ``NOTICE.md`` under which each licence's full text
#: is reproduced, fenced, byte-for-byte. ``NOTICE.md`` is the master; every
#: distribution's ``LICENSES/`` copy is checked against it.
_NOTICE_HEADINGS = {
    "LICENSES/BSD-3-Clause.txt": "## Full text: BSD-3-Clause",
    "LICENSES/Apache-2.0.txt": "## Full text: Apache License 2.0",
}


def _notice_full_text(rel: str) -> bytes:
    """The fenced full text of licence ``rel`` as the root ``NOTICE.md`` holds it."""
    notice = (ROOT / "NOTICE.md").read_bytes()
    heading = _NOTICE_HEADINGS[rel].encode("utf-8")
    start = notice.index(heading)
    fence = b"```text\n"
    body = notice.index(fence, start) + len(fence)
    end = notice.index(b"\n```\n", body) + 1
    return notice[body:end]


class LicenseFilesDeclared(unittest.TestCase):
    """Every ``license-files`` entry a distribution declares exists, and each
    ``LICENSES/`` copy matches its full text in the root ``NOTICE.md`` (the SODA-2- and
    Process2D-derived code is BSD-3-Clause)."""

    def test_declared_licence_files_exist_and_copies_match_the_master(self):
        import hashlib
        import tomllib
        checked = 0
        for root in _distribution_roots():
            with open(root / "pyproject.toml", "rb") as fh:
                declared = tomllib.load(fh)["project"].get("license-files", [])
            for rel in declared:
                path = root / rel
                self.assertTrue(path.is_file(), f"{path} is declared and missing")
                if rel.startswith("LICENSES/"):
                    self.assertEqual(path.read_bytes(), _notice_full_text(rel),
                                     f"{path} differs from its full text in NOTICE.md")
                    checked += 1
                if rel == "LICENSES/Apache-2.0.txt":
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                                     _APACHE_2_SHA256)
        self.assertGreaterEqual(checked, 4, "the sweep found too few LICENSES/ copies")

    def test_bsd_text_keeps_ucar_notice_verbatim(self):
        ucar = ROOT / "SODA2" / "abansemer-soda2-afcea15" / "LICENSE.txt"
        if not ucar.is_file():
            self.skipTest("The vendored SODA-2 tree is not distributed with the package")
        self.assertIn(ucar.read_text(encoding="utf-8").strip(),
                      _notice_full_text("LICENSES/BSD-3-Clause.txt").decode("utf-8"))
