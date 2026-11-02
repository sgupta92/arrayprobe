# SPDX-License-Identifier: BSD-3-Clause
"""The version string is one fact, held in three places, checked against itself.

The package sat at ``0.0.0.dev0`` for the whole of
its development, which tells a reviewer nothing about what they have in front
of them. The first release is ``0.1.0`` (decided 2026-10-08), and the
``0`` is load-bearing:

* **What ``0.1.0`` claims.** The package is usable and open: the ORACLES 2D-S
  lineage is feature-complete and reproduces the archived MATLAB products cell
  by cell across whole flights, and shattering reacceptance and
  ``iaThreshType`` cover non-ORACLES campaigns.
* **What ``0.x`` withholds.** The interface may still change before 1.0.
  Stock-tree ``sizeDist`` control flow is not implemented, and the
  probes with no UIOOPS product on this machine -- 2DC, 2DP, CIP, PIP, Fast2DC
  -- are checked against Octave oracles and synthetic fixtures only, never
  against a real product. Neither is a bug; both are things a reader of
  "1.0.0" would reasonably assume were done.

The reason this file exists rather than a note somewhere is the project's
standing rule that a recurring mechanical obligation gets a check, not a rule
(the project's guard doctrine). A version lives in the
module *and* in the packaging metadata, nothing forces an editor of one to
touch the other, and a package whose installed metadata says one thing and
whose ``__version__`` says another is worse than one that never moved.

**The two sides come from different places on purpose**: the module is read by
importing it, ``pyproject.toml`` is read as text and parsed as TOML, and the
installed distribution is read through ``importlib.metadata`` -- i.e. from the
``.dist-info`` written at install time, not from either source file. Comparing
the module against itself would test nothing.
"""

from __future__ import annotations

import re
import tomllib
import unittest
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from pathlib import Path

import arrayprobe

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
#: The repository root, one level above python_port/ -- CITATION.cff lives
#: there, not shipped in the sdist (a repository artefact, not package data),
#: so the check below skips rather than fails when it is absent.
CITATION = Path(__file__).resolve().parents[1] / "CITATION.cff"

#: PEP 440, restricted to the shapes this project intends to use: a release, or
#: a release candidate / beta / alpha of one. Deliberately narrower than the
#: full grammar -- a local version or a dev segment on a published package
#: would be a mistake worth failing on, not a variant to accommodate.
PEP440 = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?$")


class VersionIsCoherent(unittest.TestCase):
    def _pyproject_version(self) -> str:
        with open(PYPROJECT, "rb") as fh:
            return tomllib.load(fh)["project"]["version"]

    def test_module_and_pyproject_agree(self):
        """The two in-repo sides. This one holds in a fresh clone, installed or not."""
        self.assertEqual(
            arrayprobe.__version__, self._pyproject_version(),
            "src/arrayprobe/__init__.py's __version__ and pyproject.toml's "
            "[project].version have drifted. They are the same fact; change both "
            "in one commit.")

    def test_every_engine_package_carries_the_distribution_version(self):
        """``arrayprobe_uiops`` and ``arrayprobe_soda2`` ship in the same distribution, so a
        different ``__version__`` there (they said ``0.0.1.dev0`` until the 2026-09-27
        pre-release audit) tells a user the wrong thing about what they installed."""
        import arrayprobe_soda2
        import arrayprobe_uiops
        for mod in (arrayprobe_uiops, arrayprobe_soda2):
            self.assertEqual(mod.__version__, self._pyproject_version(), mod.__name__)

    def test_installed_metadata_agrees(self):
        """The third side: what ``pip`` actually recorded for the distribution.

        This is the one that catches a version bumped in the sources but never
        installed -- including the editable install on a development machine,
        whose ``.dist-info`` is written once and does not follow later edits to
        ``pyproject.toml``. If this fails and the previous test passed, the fix
        is ``pip install -e .`` from the repository root, not a change to the code.
        """
        try:
            recorded = installed_version("arrayprobe")
        except PackageNotFoundError:  # pragma: no cover -- not installed at all
            self.skipTest("arrayprobe is not installed; nothing to compare against")
        self.assertEqual(
            recorded, arrayprobe.__version__,
            f"the installed distribution says {recorded!r} but the module says "
            f"{arrayprobe.__version__!r}. Re-run `pip install -e .` from the repository root "
            "(the editable install's .dist-info does not track pyproject.toml edits).")

    def test_citation_cff_agrees(self):
        """The fourth side, added when ``scripts/release.py`` started writing it.

        ``CITATION.cff`` is the file GitHub's "Cite this repository" button
        reads and the one Zenodo populates a DOI record from, so a version it
        does not carry to the same place as the other three is a citation a
        reader can no longer trust. Read as text with a regex, not parsed as
        YAML -- this project adds no PyYAML dependency for one field.
        """
        if not CITATION.is_file():
            self.skipTest(f"{CITATION} not present -- nothing to compare against "
                           "(a repository artefact, not shipped in the sdist)")
        text = CITATION.read_text(encoding="utf-8")
        m = re.search(r"^version:\s*(\S+)\s*$", text, re.M)
        self.assertIsNotNone(m, "CITATION.cff has no 'version:' line")
        self.assertEqual(
            m.group(1), arrayprobe.__version__,
            f"CITATION.cff says version {m.group(1)!r} but the module says "
            f"{arrayprobe.__version__!r} -- they are the same fact, change both "
            "in one commit (scripts/release.py does this automatically).")

    def test_the_placeholder_version_is_gone(self):
        """``0.0.0.dev0`` was the never-moving placeholder the review packet named."""
        self.assertNotEqual(arrayprobe.__version__, "0.0.0.dev0")
        self.assertNotEqual(self._pyproject_version(), "0.0.0.dev0")

    def test_the_version_is_a_shape_this_project_uses(self):
        self.assertRegex(arrayprobe.__version__, PEP440)

    def test_the_version_does_not_claim_1_0(self):
        """While the interface may still change, the major version is ``0``
        rather than reading as a finished 1.0. Drop this test in the commit
        that cuts 1.0.0."""
        self.assertTrue(
            arrayprobe.__version__.startswith("0."),
            "the major version is no longer 0. If 1.0.0 is genuinely being "
            "cut, the review packet's two open findings and the unvalidated probes need an "
            "answer first -- see this module's docstring.")


if __name__ == "__main__":
    unittest.main()
