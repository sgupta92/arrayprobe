# SPDX-License-Identifier: BSD-3-Clause
"""The commands the shipped README gives name things the release ships.

The release's ``README.md`` is built from ``docs/developer/PACKAGE_README.md`` by the
release builder. Two defects reached it unseen: an
install command that did not install ``enhancements_soda2``, a package the release ships, and a
Test section whose ``ruff check`` named a ``tools/`` directory the release does not have.

The two sides come from different places. Side A is the commands in the README's fenced
``bash`` and ``powershell`` blocks. Side B is the set of files the release ships: in a
checkout, the builder's own
file-set rules (its allow-list, ``allowed``, ``never_ship``) over ``git ls-files``;
in a built release tree (no builder), every file present. The checks:

(a) every path argument of every ``ruff check`` and every ``unittest discover -s`` names a
    directory that ships at least one file;
(b) every ``-e <dir>`` of an install command names a shipped directory with a ``pyproject.toml``;
(c) every shipped top-level directory with its own ``pyproject.toml`` (an installable package)
    appears as ``-e <dir>`` in both the Linux/macOS and the Windows install line.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shlex
import subprocess
import sys
import unittest
from pathlib import Path

from tests._repo import repo_only

ROOT = Path(__file__).resolve().parents[1]
DEV_README = ROOT / "docs" / "developer" / "PACKAGE_README.md"
BUILDER = ROOT / "scripts" / "build_release_tree.py"
ALLOWLIST = ROOT / "scripts" / "release_allowlist.txt"

FENCE = re.compile(r"^```(?:bash|sh|shell|console|powershell|pwsh)\s*$\n(.*?)^```\s*$", re.M | re.S)
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules"}


def readme_commands(text: str) -> list[list[str]]:
    """Every command in the fenced bash blocks, as argv lists (``&&``/``;`` split, comments cut)."""
    commands = []
    for block in FENCE.findall(text):
        for line in block.splitlines():
            if not line.strip():
                continue
            lex = shlex.shlex(line, posix=True, punctuation_chars=";&|")
            lex.whitespace_split = True
            lex.commenters = "#"
            current: list[str] = []
            for tok in lex:
                if tok in {"&&", ";", "||", "|", "&"}:
                    if current:
                        commands.append(current)
                    current = []
                else:
                    current.append(tok)
            if current:
                commands.append(current)
    return commands


def _after(argv: list[str], *seq: str) -> list[str] | None:
    """The arguments after the first occurrence of ``seq`` in ``argv``, or None."""
    n = len(seq)
    for i in range(len(argv) - n + 1):
        if tuple(argv[i:i + n]) == seq:
            return argv[i + n:]
    return None


def _norm(d: str) -> str:
    d = d.replace("\\", "/").strip()
    while d.startswith("./"):
        d = d[2:]
    return d.rstrip("/") or "."


def lint_and_discover_dirs(commands: list[list[str]]) -> list[str]:
    dirs = []
    for argv in commands:
        rest = _after(argv, "ruff", "check")
        if rest is not None:
            dirs += [a for a in rest if not a.startswith("-")]
        rest = _after(argv, "unittest", "discover")
        if rest is not None:
            for i, a in enumerate(rest):
                if a == "-s" and i + 1 < len(rest):
                    dirs.append(rest[i + 1])
                elif a.startswith("--start-directory="):
                    dirs.append(a.split("=", 1)[1])
    return dirs


def install_commands(commands: list[list[str]]) -> list[tuple[list[str], list[str]]]:
    """(argv, editable targets) for every ``pip install`` command."""
    out = []
    for argv in commands:
        rest = _after(argv, "pip", "install")
        if rest is None:
            continue
        targets = [rest[i + 1] for i, a in enumerate(rest[:-1]) if a == "-e"]
        out.append((argv, [_norm(re.sub(r"\[.*\]$", "", t)) for t in targets]))
    return out


def problems(text: str, shipped: set[str]) -> list[str]:
    """Every way the README's commands disagree with the shipped file set ``shipped``."""
    dirs = {"."}
    for f in shipped:
        parts = f.split("/")[:-1]
        for k in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:k]))
    commands = readme_commands(text)
    found = []
    # (a)
    for d in lint_and_discover_dirs(commands):
        if _norm(d) not in dirs:
            found.append(f"(a) ruff/unittest names {d!r}, which ships no file")
    # (b)
    installs = install_commands(commands)
    for _argv, targets in installs:
        for t in targets:
            pyproject = "pyproject.toml" if t == "." else f"{t}/pyproject.toml"
            if pyproject not in shipped:
                found.append(f"(b) install -e {t!r}: no shipped {pyproject}")
    # (c)
    packages = sorted(f.split("/")[0] for f in shipped
                      if f.count("/") == 1 and f.endswith("/pyproject.toml"))
    posix = [t for argv, t in installs if any("/bin/" in a for a in argv)]
    windows = [t for argv, t in installs if any("Scripts" in a for a in argv)]
    for platform, lines in (("Linux/macOS", posix), ("Windows", windows)):
        if not lines:
            found.append(f"(c) no {platform} install line in the README")
            continue
        for pkg in packages:
            if not any(pkg in targets for targets in lines):
                found.append(f"(c) the {platform} install line does not install {pkg!r}")
    return found


def _load_builder():
    name = "build_release_tree"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, BUILDER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


def shipped_files() -> set[str]:
    if BUILDER.is_file() and ALLOWLIST.is_file() and (ROOT / ".git").exists():
        brt = _load_builder()
        rules = brt.parse_allowlist(ALLOWLIST.read_text(encoding="utf-8"))
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                             check=True).stdout.decode("utf-8")
        return {p for p in out.split("\0")
                if p and brt.allowed(p, rules) and not brt.never_ship(p)}
    files = set()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel = Path(dirpath).relative_to(ROOT).as_posix()
        for f in filenames:
            files.add(f if rel == "." else f"{rel}/{f}")
    return files


def readme_text() -> str:
    path = DEV_README if DEV_README.is_file() else ROOT / "README.md"
    return path.read_text(encoding="utf-8")


@repo_only
class TheShippedReadmeCommandsNameShippedThings(unittest.TestCase):
    def test_every_command_names_what_the_release_ships(self):
        text = readme_text()
        self.assertTrue(install_commands(readme_commands(text)),
                        "no pip install command found in the README's bash blocks")
        self.assertTrue(lint_and_discover_dirs(readme_commands(text)),
                        "no ruff check or unittest discover command found in the README")
        self.assertEqual(problems(text, shipped_files()), [])

    def test_the_ship_set_holds_both_enhancement_packages(self):
        shipped = shipped_files()
        for pkg in ("enhancements_uiops", "enhancements_soda2"):
            self.assertIn(f"{pkg}/pyproject.toml", shipped)


SHIPPED = {"pyproject.toml", "src/arrayprobe/__init__.py", "tests/test_x.py",
           "scripts/build.py", "enhancements_uiops/pyproject.toml",
           "enhancements_uiops/src/e/__init__.py", "enhancements_soda2/pyproject.toml",
           "docs/notes/readme.md"}

_EDITABLE = '-e ".[pinned]" -e enhancements_uiops -e enhancements_soda2'

GOOD = f"""\
```bash
python3.12 -m venv .venv && .venv/bin/python -m pip install {_EDITABLE}    # Linux
py -3.12 -m venv .venv && .venv\\Scripts\\python.exe -m pip install {_EDITABLE}  # Windows
```

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m ruff check src tests scripts enhancements_uiops enhancements_soda2
```
"""


class TheGuardFires(unittest.TestCase):
    def test_a_correct_readme_passes(self):
        self.assertEqual(problems(GOOD, SHIPPED), [])

    def test_a_ruff_path_the_release_does_not_have_fires(self):
        bad = GOOD.replace("ruff check src tests", "ruff check src tests tools")
        self.assertEqual([p[:3] for p in problems(bad, SHIPPED)], ["(a)"])
        self.assertIn("'tools'", problems(bad, SHIPPED)[0])

    def test_a_discover_start_directory_the_release_does_not_have_fires(self):
        bad = GOOD.replace("discover -s tests", "discover -s python_port/tests")
        self.assertEqual([p[:3] for p in problems(bad, SHIPPED)], ["(a)"])

    def test_an_editable_install_of_a_directory_with_no_pyproject_fires(self):
        bad = GOOD.replace("-e enhancements_soda2  # Windows",
                           "-e enhancements_soda2 -e docs/notes  # Windows")
        self.assertEqual([p[:3] for p in problems(bad, SHIPPED)], ["(b)"])

    def test_a_shipped_package_missing_from_the_windows_line_fires(self):
        bad = GOOD.replace(" -e enhancements_soda2  # Windows", "  # Windows")
        found = problems(bad, SHIPPED)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith("(c) the Windows"), found)

    def test_a_shipped_package_missing_from_the_linux_line_fires(self):
        bad = GOOD.replace(" -e enhancements_soda2    # Linux", "    # Linux")
        found = problems(bad, SHIPPED)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith("(c) the Linux"), found)

    def test_a_missing_platform_install_line_fires(self):
        bad = "\n".join(line for line in GOOD.splitlines() if "Windows" not in line)
        self.assertEqual(problems(bad, SHIPPED), ["(c) no Windows install line in the README"])


if __name__ == "__main__":
    unittest.main()

PRESUITE_GUARD = True
