# SPDX-License-Identifier: BSD-3-Clause
"""Generate the fidelity-profile reference table from ``profiles.PROFILES``.

Plan S4C ("Reference (generated): ... the fidelity-profile table (from
``profiles.PROFILES``)"). A :class:`~arrayprobe.profiles.FidelityProfile` is
the answer to "faithful to which MATLAB variant", and it is a required
argument everywhere it matters (``profiles.py``'s own module docstring: "no
field gets a 'sensible' default that silently picks a side"). A reader
deciding which profile a new campaign needs should not have to read the
source to see what the shipped ones actually set.

Field values come from a real import (``profiles.py`` has no import-time side
effects, unlike ``triage_server`` or the CLI, so this is safe where
``apidoc.py``'s AST-only approach is not). Field *meanings* come from AST,
the same way ``apidoc.py`` reads module/class/function docstrings -- Python
does not attach a runtime docstring to a dataclass field, so the one-line
comment immediately after each field in the source is read from the syntax
tree instead of reconstructed by hand.

Usage, from the repository root::

    .venv/Scripts/python.exe docs/_build/profiledoc.py [--check]
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGE = ROOT.parent / "06-configuration.md"
# FidelityProfile itself lives in arrayprobe_uiops.profiles since split slice 10a(i).
SRC = ROOT.parents[1] / "src" / "arrayprobe_uiops" / "profiles.py"

sys.path.insert(0, str(ROOT.parents[1] / "src"))
from arrayprobe import profiles  # noqa: E402

#: The profiles the v3.5 engine runs under. The public package ships the v3.5 and
#: SODA-2 engines only, so the v3.1.4 profiles (stock-v3.1.4, oracles-2016,
#: oracles-production) are left off this page; they stay in profiles.SHIPPED.
PUBLIC = frozenset({"stock-v3.5", "oracles-production-v3.5"})

#: An in-repository upstream tree cited in a description, e.g.
#: " (UIOPS-v3.5/joefinlon-UIOPS-039be82/)": not shipped, so not cited publicly.
_TREE_CITE = re.compile(r"\s*\(UIOPS-v3\.[0-9.]+/[^)]*\)")

_MARKER_START = "<!-- PROFILEDOC:START -->"
_MARKER_END = "<!-- PROFILEDOC:END -->"


def _field_docs() -> dict[str, str]:
    """The one-line comment following each field in ``FidelityProfile``'s
    own source, keyed by field name. ``None`` for the two identity fields
    (``name``, ``description``), which document themselves."""
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for node in tree.body:
        if not (isinstance(node, ast.ClassDef) and node.name == "FidelityProfile"):
            continue
        body = node.body
        for i, stmt in enumerate(body):
            if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                continue
            doc = ""
            nxt = body[i + 1] if i + 1 < len(body) else None
            if isinstance(nxt, ast.Expr) and isinstance(nxt.value, ast.Constant):
                doc = str(nxt.value.value).strip().splitlines()[0]
                doc = re.sub(r"``([^`]+)``", r"`\1`", doc)  # reST inline literal -> markdown
            out[stmt.target.id] = doc
    return out


#: Shown between the field table and the values table.
PROFILE_LEGEND = [
    "**How to read the values table.** One row per field (meanings above), one column "
    "per shipped profile. `reject_thresholds` is split into one row per threshold, "
    "written `reject_thresholds.<name>`. A value is the field's literal Python value "
    "(`True`/`False`, a string in quotes, a number).",
    "",
]


def render() -> str:
    field_docs = _field_docs()
    lines = [_MARKER_START, ""]
    all_fields = [f for f in dataclasses.fields(profiles.FidelityProfile)
                  if f.name not in ("name", "description")]

    lines.append("| Field | What it means |")
    lines.append("|---|---|")
    for f in all_fields:
        lines.append(f"| `{f.name}` | {field_docs.get(f.name, '')} |")
    lines.append("")

    # SHIPPED, not PROFILES -- and this is a reproducibility fix, not a filter.
    # profiles.PROFILES is the LIVE registry: register_profile() mutates it, so importing
    # any fork's profile module (arrayprobe_uiops.register_image_assisted, an ARM-ENA profile)
    # adds rows here. That made this generated table depend on which modules happened to be
    # imported in the process -- it rendered one way alone and another way inside the full
    # suite, where other tests import those modules. Measured 2026-09-19: bare gives 5
    # profiles, one import gives 6, and the checked-in doc then disagreed with a fresh build
    # in the suite while matching it standalone. A generated surface whose content depends on
    # import order is not reproducible, which is the whole property this table is built for.
    shipped = sorted(
        (nm, pr) for nm, pr in profiles.PROFILES.items()
        if nm in profiles.SHIPPED and nm in PUBLIC)

    # One row per field and one column per profile (a table that is
    # easier to read than a ten-column row per profile). A nested dataclass field
    # (`reject_thresholds`) gets one row per member, so every cell holds a single value.
    rows: list[tuple[str, list[object]]] = []
    for f in all_fields:
        first = getattr(shipped[0][1], f.name) if shipped else None
        if dataclasses.is_dataclass(first):
            for ff in dataclasses.fields(first):
                rows.append((f"{f.name}.{ff.name}",
                             [getattr(getattr(p, f.name), ff.name) for _, p in shipped]))
        else:
            rows.append((f.name, [getattr(p, f.name) for _, p in shipped]))

    lines += PROFILE_LEGEND
    lines.append("| Field |" + "".join(f" `{nm}` |" for nm, _ in shipped))
    lines.append("|---|" + "---|" * len(shipped))
    for field, values in rows:
        cells = [f"`{v!r}`" for v in values]
        lines.append(f"| `{field}` | " + " | ".join(cells) + " |")
    lines.append("")

    # SHIPPED, not PROFILES -- and this is a reproducibility fix, not a filter.
    # profiles.PROFILES is the LIVE registry: register_profile() mutates it, so importing
    # any fork's profile module (arrayprobe_uiops.register_image_assisted, an ARM-ENA profile)
    # adds rows here. That made this generated table depend on which modules happened to be
    # imported in the process -- it rendered one way alone and another way inside the full
    # suite, where other tests import those modules. Measured 2026-09-19: bare gives 5
    # profiles, one import gives 6, and the checked-in doc then disagreed with a fresh build
    # in the suite while matching it standalone. A generated surface whose content depends on
    # import order is not reproducible, which is the whole property this table is built for.
    for name, p in shipped:
        lines.append(f"**`{name}`** — {_TREE_CITE.sub('', p.description)}")
        lines.append("")

    lines.append(_MARKER_END)
    # No trailing newline here: `post` (everything after the literal END marker
    # in the file being patched) already carries whatever whitespace originally
    # followed it, and adding one here would make every regeneration insert one
    # more blank line before the next heading than the last -- caught by
    # actually running this twice in a row, not by reading the code.
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="fail if the generated block would change, without writing")
    args = ap.parse_args(argv)

    rendered = render()
    current = PAGE.read_text(encoding="utf-8")
    if _MARKER_START not in current or _MARKER_END not in current:
        print(f"PROBLEM: {PAGE} has no {_MARKER_START} .. {_MARKER_END} block to fill")
        return 1
    pre, rest = current.split(_MARKER_START, 1)
    _, post = rest.split(_MARKER_END, 1)
    updated = pre + rendered + post

    if args.check:
        if updated != current:
            print(f"STALE: {PAGE}'s generated profile table does not match "
                  "profiles.py; run docs/_build/profiledoc.py")
            return 1
        print(f"OK: {PAGE} matches profiles.py")
        return 0

    PAGE.write_text(updated, encoding="utf-8")
    print(f"wrote {PAGE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
