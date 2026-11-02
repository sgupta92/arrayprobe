# SPDX-License-Identifier: BSD-3-Clause
"""Cut a release: rewrite the three version holders, roll the changelog heading.

PEP 440
governs the shape (``tests/test_version.py``'s ``PEP440`` pattern, duplicated
here rather than imported -- this script runs from a checkout that may not
have the package installed). The first release is ``0.1.0``; while MAJOR is
``0`` the interface may still change. PATCH is a fidelity correction or a tooling fix, MINOR a new
reader/probe/preset/subcommand, MAJOR an API or profile-semantics break.

**The three holders, and why there are exactly three.** ``tests/test_version.py``
already asserts a fourth side -- the *installed* metadata -- agrees with the
module; that side is derived at install time and this script does not touch
it (the release commit's ``pip install -e .`` does). The three this script
owns are the ones a person edits: ``src/arrayprobe/__init__.py``'s
``__version__``, ``pyproject.toml``'s ``version``, and ``CITATION.cff``'s
``version`` -- the file GitHub reads for the "Cite this repository" button and
the one Zenodo populates a DOI record from.

**What this does NOT do, deliberately.** Run the suite, commit, tag or push.
Cutting a release is an author action (the tag triggers the full CI matrix,
`.github/workflows/tests.yml`), and `enhancements_uiops/pyproject.toml`'s own
version is independent after the one-time 2026-09 flip this plan describes --
a fork with its own release cadence should not have this script touch a
package it does not own.

Usage, from the repository root::

    .venv/Scripts/python.exe scripts/release.py --version 0.1.0
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "src" / "arrayprobe" / "__init__.py"
PYPROJECT = ROOT / "pyproject.toml"
CITATION = ROOT / "CITATION.cff"
CHANGES = ROOT / "docs/developer/HISTORY.md"

#: Duplicated from tests/test_version.py's PEP440 on purpose -- see this
#: module's docstring for why importing the package is not an option here.
PEP440 = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?$")


def _rewrite(path: Path, pattern: re.Pattern[str], replacement: str, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"{path} does not exist -- run this from a full checkout")
    # Bytes in, bytes out, so LF stays LF and CRLF stays CRLF. Text mode wrote
    # CRLF on Windows: a whole-file diff on CITATION.cff, which is ``-text`` in
    # .gitattributes and byte-identical to its copies (tests/test_license_copies.py).
    text = path.read_bytes().decode("utf-8")
    new_text, n = pattern.subn(replacement, text, count=1)
    if n != 1:
        raise SystemExit(
            f"could not find exactly one {label} in {path} ({n} matches) -- "
            "the file's shape has changed since this script was written")
    path.write_bytes(new_text.encode("utf-8"))
    print(f"  {path.relative_to(ROOT)}: {label} -> {replacement.strip()!r}")


def _roll_changelog(new: str, today: str) -> None:
    if not CHANGES.is_file():
        raise SystemExit(f"{CHANGES} does not exist")
    text = CHANGES.read_bytes().decode("utf-8")  # bytes-faithful, as in _rewrite
    eol = "\r\n" if "\r\n" in text else "\n"  # the file's own line ending
    marker = f"## [Unreleased]{eol}"
    if marker not in text:
        raise SystemExit(
            f"{CHANGES} has no '## [Unreleased]' heading to roll -- "
            "a release has already been cut since the last edit, or the "
            "file's shape has changed")
    text = text.replace(marker, f"{marker}{eol}## [{new}] - {today}{eol}", 1)
    CHANGES.write_bytes(text.encode("utf-8"))
    print(f"  {CHANGES.relative_to(ROOT)}: [Unreleased] content -> [{new}] - {today}, "
          "fresh empty [Unreleased] above it")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", required=True,
                         help="the new version, PEP 440 shape (e.g. 1.0.0, 1.1.0rc1)")
    args = parser.parse_args(argv)
    new = args.version
    if not PEP440.match(new):
        raise SystemExit(
            f"{new!r} is not a version shape this project uses -- see this "
            "module's PEP440 pattern")

    print(f"Rewriting the three version holders to {new!r}:")
    _rewrite(INIT, re.compile(r'__version__ = "[^"]+"'),
              f'__version__ = "{new}"', "__version__")
    _rewrite(PYPROJECT, re.compile(r'\nversion = "[^"]+"'),
              f'\nversion = "{new}"', "version")
    _rewrite(CITATION, re.compile(r'\nversion: \S+'),
              f'\nversion: {new}', "version")

    today = dt.date.today().isoformat()
    print()
    print("Rolling the changelog heading:")
    _roll_changelog(new, today)

    print()
    print("Not done here, and deliberately -- the suite, the commit, the tag and the push.")
    print("One command per line, each safe to paste into PowerShell 5.1 or Git Bash:")
    print(
        '  .venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"'
        "   # from the repository root"
    )
    print("  git add -A")
    print(f"  git commit -m \"Release {new}\"")
    print(f"  git tag -a v{new} -m \"arrayprobe {new}\"")
    print("  git push")
    print(f"  git push origin v{new}")


if __name__ == "__main__":
    main()
