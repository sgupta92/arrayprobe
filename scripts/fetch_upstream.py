# SPDX-License-Identifier: BSD-3-Clause
"""Fetch the pinned upstream trees and verify them against their tracked manifests.

The upstream trees are not vendored. For each tree in
``scripts/upstream.lock.toml`` this downloads GitHub's tarball at the pinned full SHA,
extracts **only** the files the tree's tracked ``scripts/upstream/<tree>.sha256.json`` lists, checks
every SHA-256, and prints the environment-variable lines ``tests/_upstream.py`` reads.

    python scripts/fetch_upstream.py --dest "$RUNNER_TEMP/upstream"
    python scripts/fetch_upstream.py --dest ../_upstream_scratch --tree soda2

Exit status is non-zero on any hash mismatch or missing file. An existing populated
tree is never overwritten without ``--force``. ``--tarball NAME=PATH`` reads a local
tarball instead of the network (the offline test uses it). Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import sys
import tarfile
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = Path(__file__).resolve().with_name("upstream.lock.toml")


def load_lock(path: Path = LOCK) -> dict[str, dict[str, str]]:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _download(repo: str, sha: str) -> bytes:
    url = f"https://codeload.github.com/{repo}/tar.gz/{sha}"
    with urllib.request.urlopen(url, timeout=300) as resp:  # noqa: S310 (fixed https host)
        return resp.read()


def fetch_one(name: str, entry: dict[str, str], dest: Path, *, root: Path = ROOT,
              tarball: bytes | None = None, force: bool = False) -> tuple[Path, list[str], int]:
    """Extract and verify one tree; returns (tree dir, problems, files verified)."""
    manifest: dict[str, str] = json.loads((root / entry["manifest"]).read_text(encoding="utf-8"))
    tree_dir = dest / entry["tree"]
    if tree_dir.exists() and any(tree_dir.iterdir()):
        if not force:
            return tree_dir, [f"{tree_dir}: already populated; pass --force to replace it"], 0
        shutil.rmtree(tree_dir)
    prefix = f"{entry['tree']}/{entry['inner']}/"
    wanted = {k[len(prefix):]: (k, v) for k, v in manifest.items() if k.startswith(prefix)}
    problems = [f"{k}: manifest key outside {prefix}" for k in manifest if not k.startswith(prefix)]
    data = tarball if tarball is not None else _download(entry["repo"], entry["sha"])
    found: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
        for member in tf:
            if not member.isfile():
                continue
            parts = member.name.split("/", 1)
            if len(parts) != 2 or parts[1] not in wanted:
                continue  # not in the manifest: never extracted
            rel = parts[1]
            key, expected = wanted[rel]
            fobj = tf.extractfile(member)
            if fobj is None:
                continue
            blob = fobj.read()
            target = tree_dir / entry["inner"] / rel
            if not target.resolve().is_relative_to(tree_dir.resolve()):
                problems.append(f"{key}: path escapes the destination")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
            found.add(rel)
            if hashlib.sha256(blob).hexdigest() != expected:
                problems.append(f"{key}: hash differs from the recorded provenance")
    for rel in sorted(set(wanted) - found):
        problems.append(f"{wanted[rel][0]}: in the manifest but missing from the tarball")
    verified = len(found) - sum(1 for p in problems if "hash differs" in p)
    return tree_dir, problems, verified


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", required=True, type=Path,
                    help="directory to extract into (outside the repository, e.g. $RUNNER_TEMP)")
    ap.add_argument("--tree", action="append", help="tree name from the lock (default: all)")
    ap.add_argument("--force", action="store_true", help="replace an existing populated tree")
    ap.add_argument("--lock", type=Path, default=LOCK)
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root holding the manifests")
    ap.add_argument("--tarball", action="append", default=[], metavar="NAME=PATH",
                    help="read this local tarball for NAME instead of downloading")
    ap.add_argument("--allow-in-repo", action="store_true",
                    help="permit a --dest inside the repository")
    args = ap.parse_args(argv)
    lock = load_lock(args.lock)
    dest = args.dest.resolve()
    if not args.allow_in_repo and dest.is_relative_to(args.root.resolve()):
        print(f"refusing --dest inside the repository ({dest}); pass --allow-in-repo",
              file=sys.stderr)
        return 2
    local = dict(t.split("=", 1) for t in args.tarball)
    names = args.tree or list(lock)
    failed = False
    env_lines = []
    for name in names:
        if name not in lock:
            print(f"unknown tree {name!r}; known: {sorted(lock)}", file=sys.stderr)
            return 2
        entry = lock[name]
        blob = Path(local[name]).read_bytes() if name in local else None
        tree_dir, problems, verified = fetch_one(name, entry, dest, root=args.root,
                                                 tarball=blob, force=args.force)
        total = len(json.loads((args.root / entry["manifest"]).read_text(encoding="utf-8")))
        print(f"{name}: {verified}/{total} verified at {entry['repo']}@{entry['sha']}")
        for p in problems:
            print(f"  FAIL {p}", file=sys.stderr)
        failed = failed or bool(problems)
        env_lines.append(f"{entry['env']}={tree_dir}")
    for line in env_lines:
        print(line)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
