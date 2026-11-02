# SPDX-License-Identifier: BSD-3-Clause
"""Where a test is running from: a repository checkout, or an unpacked sdist.

The sdist is built from the repository root and carries ``src/``, ``tests/``, ``scripts/``
and ``docs/*.md``, but nothing above that directory: not the vendored MATLAB/IDL trees,
``paper/`` or the root
documents. Two consequences for a test:

* A file the package ships is reached from ``PKG_ROOT`` (``python_port/`` in a
  checkout, the sdist root once unpacked), never as ``REPO_ROOT / "python_port"``,
  which exists only in a checkout.
* A test whose subject is a repository-only file carries ``@repo_only`` on its
  class or method, so an unpacked sdist reports it as skipped with the reason.

The gate is detected from the layout, not from an environment variable, so the
dist job's suite stays ungated: it sets nothing, and the tests skip because the
files are absent. ``REPO_PRESENT`` needs the directory name and two repository-root
files that ``MANIFEST.in`` can never ship (they sit above the project root). It
does not look at ``.git``; ``git_checkout_present()`` adds that for the tests that
shell out to ``git``. ``tests/test_repo_gate_is_honest.py`` checks the detector
against ``git`` itself, so a detector that silently returned False in a checkout,
skipping every gated test everywhere, fails the suite.

Like ``_hygiene.py`` and ``_slow.py``, the decorators are ``unittest.skipUnless``
on a class or method, never a ``setUpModule`` skip, so the skips are counted.
"""

from __future__ import annotations

import functools
import importlib.util
import os
import shutil
import subprocess
import unittest
from pathlib import Path

#: The repository root in a checkout (the package sits at the root since the
#: 2026-10-08 move out of ``python_port/``); the sdist's own root once unpacked.
PKG_ROOT = Path(__file__).resolve().parents[1]

#: The repository root. The same directory as ``PKG_ROOT`` on this layout; in an
#: unpacked sdist it is the sdist root, and ``REPO_PRESENT`` is False there.
REPO_ROOT = PKG_ROOT

#: Repository-root files the sdist cannot carry; both must be present. Both ship in the public
#: release tree and neither is in ``MANIFEST.in``, so a clone
#: of either repository reads as a checkout and an unpacked sdist does not.
#:
_REPO_MARKERS = (Path("CONTRIBUTING.md"), Path(".pre-commit-config.yaml"))


def repo_present(pkg_root: Path) -> bool:
    """True when ``pkg_root`` is the root of a repository checkout.

    The package sits at the repository root, so the markers are read beside
    ``tests/``. An unpacked sdist carries neither marker (``MANIFEST.in`` includes
    neither ``CONTRIBUTING.md`` nor ``.pre-commit-config.yaml``), which is what keeps this
    False there.
    The directory name is not consulted: a worktree or a clone may be named anything.
    """
    pkg_root = Path(pkg_root)
    return all((pkg_root / marker).is_file() for marker in _REPO_MARKERS)


def git_toplevel_is(root: Path) -> bool | None:
    """Whether ``git`` names ``root`` as the top of a work tree; None when git is absent."""
    git = shutil.which("git")
    if git is None:
        return None
    try:
        out = subprocess.run([git, "-C", str(root), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return False
    if out.returncode != 0 or not out.stdout.strip():
        return False
    named = os.path.normcase(str(Path(out.stdout.strip()).resolve()))
    return named == os.path.normcase(str(Path(root).resolve()))


#: True in a repository checkout, False in an unpacked sdist. Read once at import.
REPO_PRESENT = repo_present(PKG_ROOT)


@functools.cache
def git_checkout_present() -> bool:
    """The repository layout is present AND ``git`` works on it (for tests that call git)."""
    return REPO_PRESENT and bool(git_toplevel_is(REPO_ROOT))


def git_checkout_only(obj):
    """``@repo_only`` for a test that shells out to ``git`` on the repository.

    Evaluated when the decorated module is imported (one ``git`` call per process,
    cached), so a module that never uses it never runs ``git``.
    """
    return unittest.skipUnless(
        git_checkout_present(),
        "runs git on the repository checkout, which an unpacked sdist is not")(obj)


repo_only = unittest.skipUnless(
    REPO_PRESENT, "reads a repository file the sdist does not carry")

#: True where the package's source tree sits beside ``tests/``: a checkout, or an unpacked
#: sdist before the installed-package CI leg moves ``src/`` away so the suite imports the
#: wheel. A test that sweeps or parses files under ``src/`` carries ``@needs_source``; the
#: checkout leg runs it, and the installed leg reports it as skipped with the reason.
SOURCE_PRESENT = (PKG_ROOT / "src" / "arrayprobe").is_dir()

needs_source = unittest.skipUnless(
    SOURCE_PRESENT,
    "reads the package source under src/, which the installed-package run moves away")

needs_v314_engine = unittest.skipUnless(
    importlib.util.find_spec("arrayprobe.reject") is not None,
    "V3.1.4 validation engine, which is not part of the public distribution is not distributed "
    "with the package")

needs_enhancements = unittest.skipUnless(
    importlib.util.find_spec("arrayprobe_enhancements") is not None,
    "needs the arrayprobe_enhancements package, which is not installed")

#: The raw CIP/2DC ``.sea`` fixture. It is 13.6 MB of raw instrument data and does not ship in
#: the public release, so every test that opens it skips by name when it is absent.
S6_FIXTURE = Path(__file__).resolve().parent / "data" / "s6_sea_raw_fixture"

needs_s6_fixture = unittest.skipUnless(
    S6_FIXTURE.exists(),
    "Needs tests/data/s6_sea_raw_fixture is not distributed with the package")


def resolve_bash(exec_path: str | None = None, which=shutil.which,
                 windows: bool | None = None, env: dict | None = None) -> str | None:
    """Git's bash, the one the repository's hooks run with, or None (guard audit fix 4).

    The one resolver for every hook-running test (moved here from
    ``test_pretool_dispatch._git_bash``). A bare ``["bash", ...]`` takes
    whatever ``PATH`` finds first; on Windows with WSL ahead of Git that is
    System32's WSL ``bash.exe``, which runs the hook in another filesystem, so a
    guard test passes or skips while testing nothing.

    Order: a Git-for-Windows bash path variable; off Windows, ``/bin/bash`` then
    ``PATH``. On Windows, ``bin/bash.exe`` (the launcher that puts ``usr/bin``
    and ``mingw64/bin`` on ``PATH``, so the guards' grep/sed pipelines resolve as
    under the harness), then ``usr/bin/bash.exe``, searched under the Git root
    from ``git --exec-path``, the installed ``git``'s parents, Program Files and
    ``%LOCALAPPDATA%/Programs/Git`` (never assumed to be Program Files); last, a
    ``PATH`` hit that is not System32's.
    """
    env = os.environ if env is None else env
    forced = env.get("CLAUDE_CODE_GIT_BASH_PATH")
    if forced and os.path.isfile(forced):
        return forced
    windows = (os.name == "nt") if windows is None else windows
    if not windows:
        if Path("/bin/bash").is_file():
            return "/bin/bash"
        return which("bash")
    if exec_path is None:
        try:
            exec_path = subprocess.run(
                ["git", "--exec-path"], capture_output=True, text=True,
                timeout=120).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            exec_path = ""
    roots: list[Path] = []
    if exec_path:
        roots.append(Path(exec_path).parents[2])  # <Git>/mingw64/libexec/git-core
    git = which("git")
    if git:
        roots += list(Path(git).resolve().parents)[:3]
    if env.get("ProgramFiles"):
        roots.append(Path(env["ProgramFiles"]) / "Git")
    if env.get("LOCALAPPDATA"):
        roots.append(Path(env["LOCALAPPDATA"]) / "Programs" / "Git")
    for root in roots:
        for rel in (("bin", "bash.exe"), ("usr", "bin", "bash.exe")):
            cand = root.joinpath(*rel)
            if cand.is_file():
                return str(cand)
    found = which("bash")
    if found and "system32" not in found.lower():
        return found
    return None


BASH = resolve_bash()


def require_bash(bash: str | None = BASH) -> str:
    """The resolved bash, or an AssertionError naming the gap (never a skip)."""
    if not bash:
        raise AssertionError(
            "no Git bash found (git --exec-path, /bin/bash, PATH): the hook "
            "tests cannot run, and under ARRAYPROBE_HYGIENE=1 that is a failure")
    return bash


def needs_bash(obj, bash: str | None = None, gate: bool | None = None):
    """Skip a hook-running test when bash is missing, except under the gate.

    Under ``ARRAYPROBE_HYGIENE=1`` the class is left to run, and
    :func:`require_bash` fails it, so a machine without bash cannot turn the
    hook tests into silent skips.
    """
    bash = BASH if bash is None else bash
    if gate is None:
        gate = os.environ.get("ARRAYPROBE_HYGIENE") == "1"
    if gate:
        return obj
    return unittest.skipUnless(bash, "the hook runs under bash")(obj)


def needs_file(rel: str):
    """Skip unless ``rel`` (relative to the package root) exists.

    For a cross-check against a development file the public release does not ship;
    the skip
    names the file so it is counted, not silent.
    """
    return unittest.skipUnless(
        (PKG_ROOT / rel).exists(),
        f"needs {rel}, which is not part of the public distribution")
