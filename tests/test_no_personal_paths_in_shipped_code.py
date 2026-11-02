# SPDX-License-Identifier: BSD-3-Clause
"""Shipped code names no personal machine path (release readiness).

A hard-coded author home directory, Box folder, 8.3 temp name or ``D:`` data root in a shipped
file (``tests/test_no_personal_paths.py`` covers home directories repository-wide; this adds the
rest) breaks or leaks on a fresh clone. The scan covers the package sources, ``tools``,
the enhancement packages, the docs-site sources, ``README.md`` and the example notebooks; archive,
project bookkeeping, logs and test fixtures are historical records and out of scope. A legitimate
hit (an env-overridable default) goes in ``personal_paths_allowlist.txt`` with its reason.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests._repo import repo_only

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ALLOWLIST = HERE / "personal_paths_allowlist.txt"

# Assembled from pieces so this file does not itself spell out a home
# directory (tests/test_no_personal_paths.py scans tracked tests too).
_USER = "sid" + r"\." + "gupta"
PATTERN = re.compile(
    r"C:[/\\]+Users[/\\]+" + _USER + r"|/c/" + "Users/" + _USER
    + r"|~/" + "Box" + r"|SID~1\.GUP|D:/arrayprobe",
    re.IGNORECASE,
)

SCOPE = (
    ("src", "**/*.py"),
    ("scripts", "**/*.py"),
    ("scripts", "**/*.sh"),
    ("enhancements", "**/*.py"),
    ("enhancements_soda2", "**/*.py"),
    ("docs/_build/pages", "**/*.md"),
    ("examples", "*.ipynb"),
    (".", "README.md"),
)
EXCLUDED_PARTS = {"tests", "__pycache__", ".venv", "build", "dist"}


def load_allowlist(path: Path = ALLOWLIST) -> list[tuple[str, str, str]]:
    entries: list[tuple[str, str, str]] = []
    if not path.is_file():  # not shipped: no allowed hits
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        rel, sub, reason = (p.strip() for p in line.split(" | ", 2))
        entries.append((rel, sub, reason))
    return entries


def shipped_files(root: Path = REPO):
    for base, glob in SCOPE:
        top = root / base
        if not top.is_dir():
            continue
        for f in sorted(top.glob(glob)):
            rel = f.relative_to(root)
            if f.is_file() and not (set(rel.parts[:-1]) & EXCLUDED_PARTS):
                yield f


def find_hits(root: Path = REPO, allow=None):
    """Return (unallowed hits, allow-list entries that matched nothing)."""
    allow = load_allowlist() if allow is None else allow
    used = set()
    hits = []
    for f in shipped_files(root):
        rel = f.relative_to(root).as_posix()
        text = f.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            if not PATTERN.search(line):
                continue
            ok = [i for i, (p, s, _) in enumerate(allow) if p == rel and s in line]
            if ok:
                used.update(ok)
            else:
                hits.append(f"{rel}:{n}: {line.strip()[:160]}")
    dead = [f"{p} | {s}" for i, (p, s, _) in enumerate(allow) if i not in used]
    return hits, dead


@repo_only
class TestNoPersonalPathsInShippedCode(unittest.TestCase):
    def test_shipped_code_names_no_personal_path(self):
        hits, _ = find_hits()
        self.assertEqual(hits, [], "personal machine paths in shipped code; use an env var, "
                         "a CLI argument or a relative path, or allow-list with a reason:\n"
                         + "\n".join(hits))

    def test_every_allowlist_entry_still_matches_and_has_a_reason(self):
        _, dead = find_hits()
        self.assertEqual(dead, [], "allow-list entries that match nothing")
        for rel, _sub, reason in load_allowlist():
            self.assertTrue(reason, f"{rel}: allow-list entry without a reason")

    def test_scan_reaches_files(self):
        self.assertGreater(sum(1 for _ in shipped_files()), 50)


@repo_only
class TestGuardFires(unittest.TestCase):
    def test_a_planted_personal_path_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir(parents=True)
            u = "sid" + ".gupta"
            bs = chr(92)
            planted_lines = ["X = 'C:/Users/" + "' + u",
                             "Y = 'C:" + bs + "Users" + bs + "' + u",
                             "Z = '~/Bo" + "x/Projects'",
                             "W = 'D:/array" + "probe/run'"]
            planted_lines = [ln.replace("' + u", u + "'") for ln in planted_lines]
            for planted in planted_lines:
                (root / "scripts" / "planted.py").write_text(planted + chr(10))
                hits, _ = find_hits(root, allow=[])
                self.assertEqual(len(hits), 1, planted)

    def test_an_allowlisted_line_is_not_reported_and_a_dead_entry_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "examples").mkdir()
            (root / "examples" / "n.ipynb").write_text('"p = \\"D:/arrayprobe/x\\""\n')
            allow = [("examples/n.ipynb", "D:/arrayprobe/x", "r"), ("README.md", "gone", "r")]
            hits, dead = find_hits(root, allow=allow)
            self.assertEqual(hits, [])
            self.assertEqual(dead, ["README.md | gone"])


if __name__ == "__main__":
    unittest.main()

# A repository sweep: run before every full suite by the pre-suite check
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
