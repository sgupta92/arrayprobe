# SPDX-License-Identifier: BSD-3-Clause
"""Resolve, require and verify the upstream source trees for the port suite.

The three upstream trees (UIOOPS v3.1.4, UIOOPS v3.5, SODA-2) are leaving the public
repository but stay on disk for the oracle and citation tests. Every test or tool that
reads one finds it here, never by a hard-coded path, so a checkout without a tree skips
by name instead of erroring, and a moved tree is one environment variable away.

Test and developer tooling only: nothing in ``src/`` may import this (packages must not
depend on the repository layout). ``scripts/_upstream.py`` re-exports it.

- ``tree(name)``: the tree's directory, from ``ARRAYPROBE_UIOPS314_TREE`` /
  ``ARRAYPROBE_UIOPS35_TREE`` / ``ARRAYPROBE_SODA2_TREE``, defaulting to today's repository
  paths.
- ``require(name)``: the directory if it holds files; otherwise ``unittest.SkipTest``
  whose message starts ``UPSTREAM_TREE_ABSENT: <name>``, or ``AssertionError`` when
  ``ARRAYPROBE_REQUIRE_UPSTREAM=1`` (CI, where the fetch must have happened).
- ``verify(name)``: every file the tree's tracked ``scripts/upstream/<tree>.sha256.json`` names is
  recomputed and compared; returns the list of problems (empty means byte-identical).
  The manifest is read from the repository, never from the overridden tree, so the
  check draws its two sides from different places.
"""
from __future__ import annotations

import hashlib
import json
import os
import unittest
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: name -> (environment variable, repository directory that holds the manifest and
#: whose name prefixes every manifest key).
TREES: dict[str, tuple[str, str]] = {
    "uiops314": ("ARRAYPROBE_UIOPS314_TREE", "UIOPS-v3.1.4"),
    "uiops35": ("ARRAYPROBE_UIOPS35_TREE", "UIOPS-v3.5"),
    "soda2": ("ARRAYPROBE_SODA2_TREE", "SODA2"),
}

#: name -> the pinned source directory inside the tree (the one the oracles read).
SOURCES: dict[str, str] = {
    "uiops314": "joefinlon-UIOPS-ba5e67c",
    "uiops35": "joefinlon-UIOPS-039be82",
    "soda2": "abansemer-soda2-afcea15",
}

REQUIRE_ENV = "ARRAYPROBE_REQUIRE_UPSTREAM"
_OWN_FILES = {"PROVENANCE.md", "PROVENANCE.sha256.json"}


def _entry(name: str) -> tuple[str, str]:
    try:
        return TREES[name]
    except KeyError:
        raise KeyError(f"unknown upstream tree {name!r}; known: {sorted(TREES)}") from None


def tree(name: str) -> Path:
    """The directory of upstream tree *name* (it may not exist)."""
    env, repo_dir = _entry(name)
    override = os.environ.get(env, "").strip()
    return Path(override) if override else ROOT / repo_dir


def source(name: str) -> Path:
    """The pinned source directory inside tree *name* (it may not exist)."""
    _entry(name)
    return tree(name) / SOURCES[name]


def manifest_path(name: str) -> Path:
    """The tracked hash manifest for *name*, always in the repository."""
    return ROOT / "scripts" / "upstream" / f"{_entry(name)[1]}.sha256.json"


def _present(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any(p.is_file() and p.name not in _OWN_FILES for p in path.rglob("*"))


def require(name: str) -> Path:
    """Return the tree, or skip (fail under ``ARRAYPROBE_REQUIRE_UPSTREAM=1``) by name."""
    path = tree(name)
    if _present(path):
        return path
    env = _entry(name)[0]
    msg = (f"UPSTREAM_TREE_ABSENT: {name} has no source files at {path} "
           f"(set {env} to a fetched upstream tree)")
    if os.environ.get(REQUIRE_ENV, "").strip() == "1":
        raise AssertionError(msg + f"; {REQUIRE_ENV}=1 makes absence a failure")
    raise unittest.SkipTest(msg)


def cited_path(rel: str) -> Path:
    """The file a repository-relative citation names, through the tree gate.

    ``"UIOPS-v3.5/joefinlon-UIOPS-039be82/sizeDist.m"`` resolves inside ``require("uiops35")``,
    so a checkout without that tree skips by name and an override is honoured. A path under no
    upstream tree resolves against the repository root unchanged."""
    for name, (_env, repo_dir) in TREES.items():
        if rel.startswith(repo_dir + "/"):
            return require(name) / rel[len(repo_dir) + 1:]
    return ROOT / rel


def verify(name: str, *, allow_absent: Iterable[str] = ()) -> list[str]:
    """Problems found comparing tree *name* against its manifest; [] when identical.

    *allow_absent* lists manifest keys (repository-relative, as the manifest writes
    them) that may be missing from disk -- files deliberately never committed.
    """
    mpath = manifest_path(name)
    if not mpath.is_file():
        return [f"{mpath}: manifest missing"]
    manifest: dict[str, str] = json.loads(mpath.read_text(encoding="utf-8"))
    prefix = _entry(name)[1] + "/"
    root = tree(name)
    allowed = set(allow_absent)
    problems: list[str] = []
    for key, expected in sorted(manifest.items()):
        rel = key[len(prefix):] if key.startswith(prefix) else key
        path = root / rel
        if not path.is_file():
            if key not in allowed:
                problems.append(f"{key}: in the manifest but missing from {root}")
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            problems.append(f"{key}: hash differs from the recorded provenance")
    return problems
