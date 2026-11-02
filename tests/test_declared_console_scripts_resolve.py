# SPDX-License-Identifier: BSD-3-Clause
"""Every declared console script actually resolves, and the documented rebuild is what is installed.

**WHY THIS EXISTS (2026-09-16).** Two independent findings in one night made
environment drift a class rather than an incident:

1. ``arrayprobe-soda2-enhancements`` was **not installed** in ``.venv``,
   although ``.gitignore``'s rebuild block documents
   ``pip install -e enhancements_soda2`` into that same venv. The consequence was not an
   error anywhere -- it was a *blank cell*: the readiness matrix could not measure the
   SODA-2 enhancement module count, because the package could not be imported.
2. ``arrayprobe-enhanced``'s console script was missing from that venv. The installed
   ``dist-info`` carried **no ``entry_points.txt`` at all** -- the signature of an install
   that predates commit ``41b7cce``, which added ``[project.scripts]`` to
   ``enhancements_uiops/pyproject.toml``. Console scripts are generated at install time, so the
   table can be right, the package can be importable, and the command can still not exist.
   Every document telling a reader to run it stayed silent about that.

Neither had a check. *A rule addressed to attention is
not a control; when a standing rule is found to have failed, build the check*
-- so this file is the check.

**WHAT IT ASSERTS.**

* Every ``[project.scripts]`` entry in every ``pyproject.toml`` in the repository (the three
  distributions; worktrees and venvs excluded) resolves to a real executable in the running
  interpreter's environment, via ``shutil.which``, **and** is declared in the installed
  distribution's own ``console_scripts`` entry points. The second half is what names finding
  2 precisely: an install with no ``entry_points.txt`` fails it with the dist named.
* The packages the documented rebuild installs are importable -- with the package list
  **read out of ``.gitignore``'s rebuild block**, not retyped here, so the two sides of the
  check come from different places ("a check must draw its two sides from
  different places, or it is testing nothing").

**THE SKIP RULE, AND WHY IT IS NOT A LOOPHOLE.** CI installs different subsets in different
jobs, and this module runs inside the *port's* suite, which executes in three of them:

    job / step                              what is installed when this test runs
    --------------------------------------  --------------------------------------------
    port -> "Run the suite"                 python_port only (+ dev and extra pins)
    enhancements -> "Verify the port does   python_port only: the step *uninstalls*
      not depend on the enhancements"         arrayprobe-enhancements and
                                              arrayprobe-soda2-enhancements first, on
                                              purpose -- that removal IS its subject
    dist -> "Unpack the sdist and run its   the arrayprobe sdist, in a clean venv
      suite there"

So in **every** CI context this test runs, the two enhancement distributions are absent by
design. Failing there would be wrong, and a test that fails every CI job is worse than no
test. A script whose distribution is not installed therefore **skips with a message naming
the distribution and the reason**.

**AND THE COMPANION ASSERTION, because a skip that can silently become universal is this
project's own repeat failure mode** (the protected-paths guard, the README stage check, the
usage-review script -- three guards that read fine while matching nothing;
``guards-must-be-executed`` in the user's memory notes). ``TheGuardItselfIsExercised`` below
holds the floor:

* ``arrayprobe`` is **never** skippable. It is the port's own console script, and the port
  is the package under test -- an environment that can import ``tests`` at all has it
  installed. Every context in the table above therefore *does* assert something. If that
  assertion is ever reached in an environment without it, this fails rather than skips.
* At least two ``pyproject.toml`` files with a ``[project.scripts]`` table must be found,
  and the walk must be non-empty -- so a refactor that moved the tables, or a glob that
  stopped matching, is a failure and not a quiet zero.
* The environment predicate that decides the rebuild skip is checked against synthetic
  paths, so it cannot rot into "always skip" while still reading correctly.
"""

from __future__ import annotations

import importlib
import importlib.metadata as md
import os
import re
import shutil
import sys
import sysconfig
import tomllib
import unittest
from pathlib import Path

from tests._repo import PKG_ROOT, needs_file, repo_only  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GITIGNORE = ROOT / ".gitignore"
README = ROOT / "README.md"
#: Present only in the development repository: the marker of the dev view, where
#: ``.gitignore``'s rebuild block is the documented build and must exist.
RELEASE_ALLOWLIST = ROOT / "scripts" / "release_allowlist.txt"

#: The venv the rebuild block in ``.gitignore`` describes. The documented-install check
#: below applies only when the running interpreter IS this venv; anywhere else (CI, the
#: sdist job's clean venv, a contributor's own environment) the block's instructions were
#: never the thing that built it.
DOCUMENTED_VENV = PKG_ROOT / ".venv"

#: The one script that must always resolve, in every environment that can run this file.
#: See "THE COMPANION ASSERTION" above.
ALWAYS_PRESENT_SCRIPT = "arrayprobe"
ALWAYS_PRESENT_DIST = "arrayprobe"


def _script_search_path() -> str:
    """Where to look for console scripts.

    ``sysconfig.get_path("scripts")`` first, then ``PATH``: running
    ``.venv/Scripts/python.exe -m unittest`` does **not** activate the venv, so the venv's
    ``Scripts``/``bin`` directory is often absent from ``PATH``. Searching the running
    interpreter's own script directory is what makes "resolves in *this* environment" the
    question actually asked, rather than "resolves in whatever shell happened to launch it".
    """
    return os.pathsep.join(
        p for p in (sysconfig.get_path("scripts"), os.environ.get("PATH", "")) if p
    )


def _pyproject_files() -> list[Path]:
    """Every distribution's ``pyproject.toml`` in the repository.

    Top-level directories only, hidden ones excluded -- a hidden worktrees folder holds dozens
    of full checkouts and a venv can vendor hundreds, none of which are this repository's
    declarations.
    """
    found = []
    if (ROOT / "pyproject.toml").is_file():
        found.append(ROOT / "pyproject.toml")
    for child in sorted(ROOT.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            candidate = child / "pyproject.toml"
            if candidate.is_file():
                found.append(candidate)
    return found


def _declared_scripts() -> list[tuple[Path, str, str, str]]:
    """``(pyproject, dist_name, script_name, target)`` for every ``[project.scripts]`` entry."""
    rows = []
    for path in _pyproject_files():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        project = data.get("project", {})
        dist = project.get("name", path.parent.name)
        for script, target in (project.get("scripts") or {}).items():
            rows.append((path, dist, script, target))
    return rows


def _site_dirs() -> set[Path]:
    dirs = set()
    for key in ("purelib", "platlib"):
        path = sysconfig.get_paths().get(key)
        if path:
            dirs.add(Path(path).resolve())
    return dirs


def _installed_distribution(dist: str):
    """The distribution's metadata, but only when it is a real install.

    ``importlib.metadata`` answers from **any** metadata directory reachable on
    ``sys.path``, and an editable install leaves an ``.egg-info`` behind in the source
    tree. Measured 2026-09-16: with ``arrayprobe_enhancements``' ``dist-info`` moved out
    of ``site-packages`` entirely, ``md.distribution`` still resolved -- from
    ``enhancements_uiops/src/``'s ``.egg-info``, which carries no ``entry_points.txt`` -- so a
    "not installed" environment looked *installed with no console script* and the check
    failed where it should have skipped. Requiring the metadata to live in this
    interpreter's ``site-packages`` is what separates "installed here" from "a leftover
    directory in the checkout".
    """
    # Every distribution of this name, not just the first one `sys.path` happens to reach.
    # Measured 2026-09-17: running this module after `test_docs_site` (which puts the source
    # tree on `sys.path` to import `docs/_build/apidoc.py`) made `md.distribution("arrayprobe")`
    # resolve to `src/`'s leftover `.egg-info`, whose home is not site-packages -- so the guard
    # reported the port as NOT INSTALLED and failed, in a venv where it plainly was. The
    # failure was real-looking, order-dependent, and invisible when the module ran alone.
    # Scanning every candidate removes `sys.path` order from the answer entirely.
    candidates = [d for d in md.distributions()
                  if (d.metadata["Name"] or "").lower().replace("_", "-")
                  == dist.lower().replace("_", "-")]
    if not candidates:
        return None
    sites = _site_dirs()
    fallback = None
    for found in candidates:
        try:
            home = Path(found.locate_file("")).resolve()
        except (OSError, TypeError):  # pragma: no cover - exotic loaders
            fallback = fallback or found
            continue
        if home in sites:
            return found
    return fallback


def _is_installed(dist: str) -> bool:
    return _installed_distribution(dist) is not None


def _console_scripts_of(dist: str) -> set[str]:
    found = _installed_distribution(dist)
    if found is None:
        return set()
    return {ep.name for ep in found.entry_points if ep.group == "console_scripts"}


def _rebuild_install_targets() -> list[str]:
    """The directories this venv's documented build says to ``pip install -e``."""
    return _documented_install(
        GITIGNORE.read_text(encoding="utf-8") if GITIGNORE.is_file() else "",
        README.read_text(encoding="utf-8") if README.is_file() else "",
        dev_view=RELEASE_ALLOWLIST.is_file(),
    )[1]


def _documented_install(gitignore_text: str, readme_text: str,
                        dev_view: bool) -> tuple[str, list[str]]:
    """``(source, targets)``: where the venv's build is documented, and its ``-e`` targets.

    The development repository documents it in ``.gitignore``'s rebuild block, and there
    that block is the only source (no fallback, so a reworded block fails). The release
    tree's ``.gitignore`` is built from ``release/gitignore`` and has no such block; the
    release documents its install in README.md's Install section, so that is read instead.
    Neither yields targets -> an empty list, which the caller fails on.
    """
    targets = _gitignore_install_targets(gitignore_text)
    if targets or dev_view:
        return ".gitignore's rebuild block", targets
    return "README.md's Install section", _readme_install_targets(readme_text)


def _readme_install_targets(text: str) -> list[str]:
    """The ``-e`` targets of the ``pip install`` lines in README.md's ``## Install`` section.

    ``-e ".[pinned]"`` reads as ``.``: the quotes and the extras select options, not a
    directory.
    """
    section = re.search(r"^## Install\b(.*?)(?=^## |\Z)", text, re.S | re.M)
    if section is None:
        return []
    targets = []
    for line in section.group(1).splitlines():
        if "pip install" not in line:
            continue
        for match in re.finditer(
                r"-e\s+[\"']?([A-Za-z0-9_./-]+?)(?:\[[^\]]*\])?[\"']?(?=\s|$)", line):
            target = match.group(1).rstrip("/") or "."
            if target not in targets:
                targets.append(target)
    return targets


def _gitignore_install_targets(text: str) -> list[str]:
    """The directories ``.gitignore``'s rebuild block says to ``pip install -e``.

    Read from the file rather than typed here: the point of the check is that this venv
    matches *that* documentation, so the documentation has to be one of the two sides.
    """
    # Anchored on "# Virtualenv" and the ignore line that closes the block, not on the
    # punctuation between them: the heading reads "# Virtualenv — rebuild with" with an
    # em dash, and matching that literally is how the first draft of this parser returned
    # nothing (and failed, loudly, rather than passing -- which is the point).
    block = re.search(
        r"^# Virtualenv\b(.*?)^\.venv/", text, re.S | re.M)
    if block is None:  # pragma: no cover - guarded by its own test below
        return []
    targets = []
    for match in re.finditer(r"-e\s+([A-Za-z0-9_./-]+)", block.group(1)):
        target = match.group(1).rstrip("/")
        if target not in targets:
            targets.append(target)
    return targets


def _top_level_packages(directory: str) -> list[str]:
    """The importable package names a source directory ships, from its ``src/`` layout."""
    src = ROOT / directory / "src"
    if not src.is_dir():
        return []
    return sorted(
        p.name for p in src.iterdir()
        if p.is_dir() and (p / "__init__.py").is_file()
    )


def _running_in_documented_venv(prefix: Path = None) -> bool:
    """True when the running interpreter is the venv ``.gitignore``'s block describes."""
    candidate = Path(sys.prefix if prefix is None else prefix)
    try:
        return candidate.resolve() == DOCUMENTED_VENV.resolve()
    except OSError:  # pragma: no cover - unresolvable path
        return False


class EveryDeclaredConsoleScriptResolves(unittest.TestCase):
    """Finding 2's guard: a declared script that no install ever generated."""

    def test_each_declared_script_resolves_or_names_why_it_cannot(self):
        rows = _declared_scripts()
        self.assertTrue(rows, "no [project.scripts] entries found anywhere in the repository")
        checked, skipped = [], []
        for pyproject, dist, script, target in rows:
            rel = pyproject.relative_to(ROOT).as_posix()
            if not _is_installed(dist):
                # NOT `self.skipTest` here, and that is deliberate and measured
                # (2026-09-16): raising SkipTest inside a `subTest` block is recorded as a
                # FAILURE, not a skip. Simulating CI -- hiding arrayprobe-enhancements'
                # dist-info -- made this method fail rather than skip, i.e. it would have
                # failed every CI job while passing on the author's laptop, the exact
                # "worse than no test" outcome. Skips are collected and decided once,
                # after the loop.
                skipped.append(
                    f"{script!r} (declared in {rel} by distribution {dist!r}, not installed)")
                continue
            with self.subTest(script=script, pyproject=rel):
                resolved = shutil.which(script, path=_script_search_path())
                self.assertIsNotNone(
                    resolved,
                    f"{dist} is installed but its declared console script {script!r} "
                    f"({rel} -> {target}) resolves to nothing in {sys.prefix}. Console "
                    "scripts are generated at INSTALL time, so an install predating the "
                    "[project.scripts] table exposes no command however correct the table "
                    f"is. Reinstall with: pip install -e {pyproject.parent.name} "
                    "--no-deps --no-build-isolation",
                )
                declared = _console_scripts_of(dist)
                self.assertIn(
                    script, declared,
                    f"{dist}'s installed dist-info declares console_scripts {sorted(declared)}, "
                    f"which does not include {script!r} -- the hallmark of an install made "
                    "before the [project.scripts] table existed (no entry_points.txt at all). "
                    f"Reinstall: pip install -e {pyproject.parent.name} --no-deps "
                    "--no-build-isolation",
                )
                checked.append(script)
        if not checked:
            # Reached only if NOTHING in the repository's script tables was installed --
            # which cannot happen in any context that runs this file, because the port
            # itself is the package under test. `TheGuardItselfIsExercised` asserts that
            # separately and unconditionally, so this branch can never become the silent
            # universal skip; it exists so the message is honest if it ever is reached.
            self.skipTest(
                "no declared console script's distribution is installed here "
                f"({sys.prefix}): {'; '.join(skipped)}. Every CI context that runs the "
                "port's suite installs only python_port -- the `enhancements` job "
                "uninstalls both enhancement dists before re-running this suite on "
                "purpose, and `dist` installs the sdist into a clean venv. See this "
                "module's docstring for the job table."
            )


class TheDocumentedRebuildIsWhatIsInstalled(unittest.TestCase):
    """Finding 1's guard: a package the rebuild block installs, missing from this venv."""

    @repo_only
    def test_every_package_the_rebuild_block_installs_is_importable(self):
        if not _running_in_documented_venv():
            self.skipTest(
                f"the running interpreter ({sys.prefix}) is not {DOCUMENTED_VENV}, the venv "
                "`.gitignore`'s rebuild block describes -- CI builds its environments from "
                "the workflow's own install steps, and the sdist job from a clean venv, so "
                "that block is not what produced this environment and is not what to hold "
                "it to."
            )
        source, targets = _documented_install(
            GITIGNORE.read_text(encoding="utf-8") if GITIGNORE.is_file() else "",
            README.read_text(encoding="utf-8") if README.is_file() else "",
            dev_view=RELEASE_ALLOWLIST.is_file(),
        )
        self.assertTrue(
            targets,
            f"no `pip install -e <dir>` lines found in {source} -- the "
            "check cannot derive what it is checking against, so it fails rather than "
            "passes (the same rule as the dist job's fixture count).",
        )
        missing = []
        for target in targets:
            packages = _top_level_packages(target)
            self.assertTrue(
                packages,
                f"{source} installs {target!r} but no src/ packages were "
                "found there -- the derivation broke, so this fails rather than checking "
                "nothing.",
            )
            for package in packages:
                try:
                    importlib.import_module(package)
                except ImportError as exc:
                    missing.append(f"{package} (from -e {target}): {exc}")
        self.assertEqual(
            [], missing,
            f"this venv has drifted from the install {source} documents -- these packages "
            "it installs are NOT importable:\n  " + "\n  ".join(missing)
            + f"\n\nRebuild or add them with the commands in {source}.",
        )

    @repo_only
    # The public tree's .gitignore is built from release/gitignore and has no rebuild block.
    @needs_file("release/gitignore")
    def test_the_rebuild_block_is_still_parseable(self):
        """The derivation's own guard: if .gitignore's block is reworded past this
        regex, the check above would skip or fail confusingly rather than measure."""
        self.assertTrue(
            GITIGNORE.is_file(), f"no .gitignore at {GITIGNORE}")
        targets = _gitignore_install_targets(GITIGNORE.read_text(encoding="utf-8"))
        self.assertGreaterEqual(
            len(targets), 2,
            "fewer than two `pip install -e` targets parsed out of .gitignore's rebuild "
            f"block (got {targets}); the block documents at least the root package (.) and "
            "enhancements_soda2. If the block was reworded, update "
            "_gitignore_install_targets() -- do not delete this assertion.",
        )

    @repo_only
    @needs_file("scripts/release_allowlist.txt")
    def test_the_dev_view_reads_the_gitignore_block_and_it_exists(self):
        """Where the release allowlist exists (the dev repository), the documented build is
        .gitignore's block, exactly, and README.md is never consulted."""
        source, targets = _documented_install(
            GITIGNORE.read_text(encoding="utf-8"), README.read_text(encoding="utf-8"),
            dev_view=True)
        self.assertEqual(".gitignore's rebuild block", source)
        self.assertTrue(targets, "the dev .gitignore has no rebuild block with -e targets")
        self.assertEqual(_rebuild_install_targets(), targets)


class TheDocumentedInstallSourceFailsClosed(unittest.TestCase):
    """Synthetic texts: each view reads its own source, and nothing found is nothing found."""

    README_TEXT = (
        "# pkg\n\n## Install\n\n```bash\n"
        "python3.12 -m venv .venv && .venv/bin/python -m pip install -e \".[pinned]\" "
        "-e enhancements_uiops    # Linux, macOS\n"
        "python -m venv .venv && .venv/Scripts/python.exe -m pip install -e \".[pinned]\" "
        "-e enhancements_uiops  # Windows\n```\n\n## Next\n\npip install -e elsewhere\n"
    )
    GITIGNORE_BLOCK = (
        "# Virtualenv - rebuild with:\n#   pip install -r requirements-dev.txt -e .\n"
        "#   pip install -e enhancements_soda2\n.venv/\n"
    )

    def test_release_view_reads_the_readme_install_section(self):
        source, targets = _documented_install("build/\n", self.README_TEXT, dev_view=False)
        self.assertEqual("README.md's Install section", source)
        self.assertEqual([".", "enhancements_uiops"], targets)

    def test_a_gitignore_block_wins_in_either_view(self):
        for dev_view in (True, False):
            with self.subTest(dev_view=dev_view):
                self.assertEqual(
                    (".gitignore's rebuild block", [".", "enhancements_soda2"]),
                    _documented_install(self.GITIGNORE_BLOCK, self.README_TEXT, dev_view))

    def test_dev_view_without_the_block_finds_nothing_rather_than_the_readme(self):
        self.assertEqual([], _documented_install("build/\n", self.README_TEXT, True)[1])

    def test_neither_source_finds_nothing(self):
        self.assertEqual([], _documented_install("build/\n", "# pkg\n", False)[1])
        no_pip = "## Install\n\n```bash\npython -m venv .venv\n```\n"
        self.assertEqual([], _documented_install("", no_pip, False)[1])


class TheGuardItselfIsExercised(unittest.TestCase):
    """A skip that can silently become universal is the failure mode this project has hit
    before. These assertions fail rather than skip, in every environment."""

    def test_the_ports_own_console_script_is_never_skippable(self):
        self.assertTrue(
            _is_installed(ALWAYS_PRESENT_DIST),
            f"{ALWAYS_PRESENT_DIST} is not installed, yet this test module imported -- "
            "every context that runs the port's suite installs the port.",
        )
        self.assertIsNotNone(
            shutil.which(ALWAYS_PRESENT_SCRIPT, path=_script_search_path()),
            f"the port's own console script {ALWAYS_PRESENT_SCRIPT!r} does not resolve in "
            f"{sys.prefix}. This is the assertion that keeps the skip rule above honest: if "
            "it ever skipped everywhere, this would still have to hold.",
        )
        self.assertIn(
            ALWAYS_PRESENT_SCRIPT, _console_scripts_of(ALWAYS_PRESENT_DIST),
            "the installed arrayprobe dist-info declares no console_scripts entry for "
            f"{ALWAYS_PRESENT_SCRIPT!r}.",
        )

    @repo_only
    def test_the_walk_finds_the_repositorys_script_tables(self):
        files = _pyproject_files()
        self.assertGreaterEqual(
            len(files), 3,
            f"expected at least the three distributions' pyproject.toml files, found {files}",
        )
        self.assertFalse(
            # parts relative to ROOT: the checkout itself may live under a
            # hidden worktrees directory, which is not the walk reaching one
            [p for p in files
             if {".claude", ".venv"} & set(p.relative_to(ROOT).parts)],
            "the walk reached a worktree or a venv; it must see only this repository's "
            "own distributions",
        )
        with_scripts = {
            "." if p.parent == ROOT else p.parent.name for p, _, _, _ in _declared_scripts()}
        self.assertGreaterEqual(
            len(with_scripts), 2,
            f"only {sorted(with_scripts)} declare [project.scripts]; expected at least "
            "the root package and enhancements_uiops. If a table was removed, say so here -- a "
            "shrinking walk must not pass quietly.",
        )
        self.assertIn(".", with_scripts)
        self.assertIn("enhancements_uiops", with_scripts)

    def test_the_venv_predicate_actually_discriminates(self):
        """The skip above hinges on this predicate. Checked against synthetic paths so it
        cannot rot into 'always True' (skip nothing, fail in CI) or 'always False' (skip
        everywhere, the silent-guard failure)."""
        self.assertTrue(_running_in_documented_venv(DOCUMENTED_VENV))
        self.assertFalse(_running_in_documented_venv(PKG_ROOT))
        self.assertFalse(_running_in_documented_venv(ROOT / "no" / "such" / "venv"))


if __name__ == "__main__":
    unittest.main()
