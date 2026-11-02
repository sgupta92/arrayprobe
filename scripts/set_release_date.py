# SPDX-License-Identifier: BSD-3-Clause
"""Move the release date: the three ``CITATION.cff`` ``date-released`` fields and the
current version's ``docs/developer/HISTORY.md`` heading, together.

``release.py`` stamps the changelog heading once, when it rolls ``[Unreleased]``; it never
touches ``CITATION.cff``'s ``date-released``, and re-running it would add a second heading.
A release that slips past its stamped day therefore needs every date moved at once, which
was done by hand twice before this script (2026-10-29 -> 10-30, then 10-31 -> 11-01).

Each site must match exactly once or nothing is written. ``--check`` writes nothing: it exits
1 unless the four dates agree, and, with ``--today``, unless they also equal today's date.

Usage, from the repository root::

    python scripts/set_release_date.py --date 2026-11-01
    python scripts/set_release_date.py --check --today
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
CITATIONS = ("CITATION.cff", "enhancements_uiops/CITATION.cff", "enhancements_soda2/CITATION.cff")
HISTORY = "docs/developer/HISTORY.md"
DATE = rb"(\d{4}-\d{2}-\d{2})"


def _version() -> str:
    m = re.search(r'(?m)^version = "([^"]+)"', PYPROJECT.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit(f"refused: no version in {PYPROJECT.name}")
    return m.group(1)


def _sites() -> list[tuple[Path, re.Pattern[bytes]]]:
    heading = re.compile(rb"(?m)^## \[" + re.escape(_version().encode()) + rb"\] - " + DATE)
    cff = re.compile(rb"(?m)^date-released: '" + DATE + rb"'")
    return [(ROOT / c, cff) for c in CITATIONS] + [(ROOT / HISTORY, heading)]


def _read() -> list[tuple[Path, bytes, re.Match[bytes]]]:
    """Each site's bytes and its one match; refuses (exit 2) unless every site matches once."""
    out = []
    for path, pat in _sites():
        if not path.is_file():
            raise SystemExit(f"refused: {path.relative_to(ROOT)} is missing")
        data = path.read_bytes()
        found = list(pat.finditer(data))
        if len(found) != 1:
            raise SystemExit(f"refused: {path.relative_to(ROOT)} has {len(found)} date sites, "
                             "expected 1; nothing written")
        out.append((path, data, found[0]))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--date", help="the release date to write, YYYY-MM-DD")
    mode.add_argument("--check", action="store_true", help="write nothing; exit 1 on disagreement")
    parser.add_argument("--today", action="store_true",
                        help="with --check: the dates must also equal today's date")
    args = parser.parse_args(argv)

    sites = _read()
    dates = {p.relative_to(ROOT).as_posix(): m.group(1).decode() for p, _, m in sites}
    if args.check:
        for name, d in dates.items():
            print(f"  {name}: {d}")
        want = dt.date.today().isoformat() if args.today else None
        if len(set(dates.values())) != 1:
            print("FAIL: the release dates disagree")
            return 1
        if want and want not in dates.values():
            print(f"FAIL: the release date is not today ({want})")
            return 1
        print("OK: the release dates agree" + (" and are today" if want else ""))
        return 0

    new = dt.date.fromisoformat(args.date).isoformat().encode()
    for path, data, m in sites:
        path.write_bytes(data[:m.start(1)] + new + data[m.end(1):])
        print(f"  {path.relative_to(ROOT).as_posix()}: {m.group(1).decode()} -> {new.decode()}")
    # Read back: a write that did not land fails here rather than printing success.
    after = {m.group(1) for _, _, m in _read()}
    if after != {new}:
        print(f"FAIL: read back {sorted(after)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
