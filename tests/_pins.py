# SPDX-License-Identifier: BSD-3-Clause
"""Exact dependency pins, read from wherever this tree keeps them.

The development repository keeps ``requirements.txt``, ``requirements-dev.txt`` and
``requirements-extra.txt``; the public tree does not ship them, because pyproject.toml's
``[pinned]`` extra repeats their pins exactly. A test that needs a pin calls
:func:`pinned_version` and gets the same answer in either tree.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
REQUIREMENTS_FILES = ("requirements.txt", "requirements-dev.txt", "requirements-extra.txt")


def requirements_files_present() -> bool:
    """True in the development repository, where the three pin files exist."""
    return all((REPO_ROOT / name).is_file() for name in REQUIREMENTS_FILES)


def pinned_extra() -> dict[str, str]:
    """``{distribution: version}`` from pyproject.toml's ``[pinned]`` extra."""
    with PYPROJECT.open("rb") as handle:
        project = tomllib.load(handle)["project"]
    pins: dict[str, str] = {}
    for requirement in project.get("optional-dependencies", {}).get("pinned", []):
        match = re.fullmatch(r"\s*([A-Za-z0-9_.\-]+)\s*==\s*([0-9][0-9A-Za-z.]*)\s*", requirement)
        if match:
            pins[match.group(1).lower()] = match.group(2)
    return pins


def pinned_version(distribution: str, requirements_file: str | None = None) -> str | None:
    """The exact pinned version of ``distribution``.

    Reads ``requirements_file`` (relative to the repository root) when it exists, and
    pyproject.toml's ``[pinned]`` extra otherwise.
    """
    if requirements_file is not None:
        path = REPO_ROOT / requirements_file
        if path.is_file():
            pattern = rf"^{re.escape(distribution)}==([0-9][0-9A-Za-z.]*)\s*$"
            text = path.read_text(encoding="utf-8")
            match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
            return match.group(1) if match else None
    return pinned_extra().get(distribution.lower())
