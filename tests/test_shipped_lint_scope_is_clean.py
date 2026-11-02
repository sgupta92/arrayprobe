# SPDX-License-Identifier: BSD-3-Clause
"""The shipped CI's lint step passes on the tree this suite runs in.

The public repository's first push runs the shipped workflow's ``Lint`` step,
``python -m ruff check <paths>``. On 2026-10-25 that command was clean in the
development tree and failed on the built public tree: two function-local import
blocks mixed a module the release leaves out (``arrayprobe.imgproc``, and the
registration import beside ``arrayprobe.profiles``) with shipped ones, so ruff's
import sorter classified them differently once the left-out module was gone. The
preview repository's last CI run had failed on the same step, and nothing local
ran the shipped lint command against the built tree. This test reads that command
from the shipped workflow and runs it where the suite runs, so the public-tree
suite fails on it before the public repository does.
"""
from __future__ import annotations

import importlib.util
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._repo import PKG_ROOT, repo_only  # noqa: E402

_STEP = re.compile(r"^\s*python -m ruff check ([^\n#]+)$", re.M)


def shipped_workflow(root: Path) -> Path:
    """The workflow file the public repository runs: ``release/workflows/`` in the development
    tree, where it waits to be copied, and ``.github/workflows/`` in the built tree."""
    staged = root / "release" / "workflows" / "tests.yml"
    return staged if staged.is_file() else root / ".github" / "workflows" / "tests.yml"


def lint_paths(workflow: Path) -> list[str]:
    found = _STEP.findall(workflow.read_text(encoding="utf-8"))
    if len(found) != 1:
        raise AssertionError(
            f"{workflow}: expected one 'python -m ruff check' step, found {len(found)}")
    return shlex.split(found[0])


def run_lint(root: Path, paths: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "ruff", "check", "--no-cache", *paths],
                          cwd=root, capture_output=True, text=True, timeout=300)


@unittest.skipUnless(importlib.util.find_spec("ruff"),
                     "ruff is not installed (pip install \"arrayprobe[dev]\")")
class ShippedLintScopeIsClean(unittest.TestCase):
    def test_the_check_fails_on_an_unsorted_import_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[tool.ruff.lint]\nselect = ["I"]\n',
                                                  encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "m.py").write_text("import sys\nimport os\n", encoding="utf-8")
            self.assertNotEqual(run_lint(root, ["src"]).returncode, 0)
            (root / "src" / "m.py").write_text("import os\nimport sys\n", encoding="utf-8")
            self.assertEqual(run_lint(root, ["src"]).returncode, 0)

    @repo_only  # the workflow file is in the repository and the built tree, not in an sdist
    def test_the_shipped_lint_step_passes_here(self):
        paths = lint_paths(shipped_workflow(PKG_ROOT))
        self.assertIn("src", paths)
        done = run_lint(PKG_ROOT, [p for p in paths if (PKG_ROOT / p).exists()])
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-1000:])


if __name__ == "__main__":
    unittest.main()
