# SPDX-License-Identifier: BSD-3-Clause
"""Release-to-release regression diff with a changed-cell log.

Compare two output directories, one produced by the previous release and one by the
new release, on the same inputs::

    python scripts/release_regression.py --old-dir A --new-dir B --out CHANGED_CELLS.md

Every netCDF file (``.nc``, ``.nc4``, ``.cdf``) present in both directories under the same relative
path is compared variable by variable.  Every changed cell is written to ``--out`` as
``(file, variable, index, old, new)``, together with the changed attributes, files present on
one side only, and variables present on one side only.  The ``Creation Time`` attribute
(global or per variable) is non-deterministic and is excluded.

The per-variable verdict reuses :func:`arrayprobe.compare.compare_variables` with every
variable put in the bit-equality class ``A`` (NaN equals NaN), so the notion of "equal" is
the package's own; only the cell enumeration for a variable that differs is local, because
the comparison module reports counts and first offenders, not every cell.

**The changes file** is the package's release history, ``docs/developer/HISTORY.md``, by
default (``--changes`` names another).  It is in Keep a Changelog shape: one ``## `` heading per
release (``## [Unreleased]``, then ``## [0.1.0] - <date>`` and so on), with ``### `` subsections
inside each, newest at the top.

**The naming rule** (deliberately simple).  The new version's section of the changes file is
the first ``## `` section, ``### `` subsections included, or the first whose heading contains
``--version``.  A change is *named* when the file's relative path (forward slashes)
appears in that section's text, or the variable's (or attribute's) name appears there in
backticks (`` `name` ``); a bare word in prose does not count, so a common variable name such as
``time`` is not named by a sentence that merely uses the word.
A global-attribute change is named by the attribute name or the path.  Exit
status: 0 when every change is named (or there is none), 1 when any change is not named,
2 on a usage error.  The log marks each change ``named`` or ``UNNAMED``.

Reads only; writes nothing but ``--out``.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from arrayprobe.compare import JoinResult, compare_variables

#: The release history this script reads unless ``--changes`` names another file.
DEFAULT_CHANGES = Path(__file__).resolve().parents[1] / "docs" / "developer" / "HISTORY.md"

NETCDF_SUFFIXES = (".nc", ".nc4", ".cdf")
EXCLUDED_ATTRIBUTES = frozenset({"Creation Time"})
GLOBAL = "<global>"


@dataclass
class Change:
    """One difference: a cell, an attribute, a variable or a file."""

    kind: str  # cell | attribute | variable | file | shape | error
    file: str
    variable: str = ""
    index: str = ""
    old: str = ""
    new: str = ""
    named: bool = False


@dataclass
class Result:
    n_files_compared: int = 0
    n_variables_compared: int = 0
    n_cells_compared: int = 0
    changes: list[Change] = field(default_factory=list)


def _fmt(v) -> str:
    if isinstance(v, (bytes, np.bytes_)):
        return repr(bytes(v))
    if isinstance(v, (float, np.floating)):
        return f"{float(v):.17g}"
    if isinstance(v, np.ndarray):
        return "[" + ", ".join(_fmt(x) for x in v.ravel()) + "]"
    return str(v)


def _find_files(root: Path) -> dict[str, Path]:
    return {
        p.relative_to(root).as_posix(): p
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.suffix.lower() in NETCDF_SUFFIXES
    }


class _Pair:
    """A one-variable stand-in for a dataset, as :func:`compare_variables` reads it."""

    def __init__(self, name: str, arr: np.ndarray):
        self.variables = {name: arr}


def _attr_equal(a, b) -> bool:
    return bool(np.array_equal(np.asarray(a), np.asarray(b)))


def _attrs(obj) -> dict:
    return {k: obj.getncattr(k) for k in obj.ncattrs() if k not in EXCLUDED_ATTRIBUTES}


def _diff_attrs(file: str, var: str, a: dict, b: dict, out: list[Change]) -> None:
    for k in sorted(set(a) | set(b)):
        if k not in a:
            out.append(Change("attribute", file, f"{var}:{k}", "", "<absent>", _fmt(b[k])))
        elif k not in b:
            out.append(Change("attribute", file, f"{var}:{k}", "", _fmt(a[k]), "<absent>"))
        elif not _attr_equal(a[k], b[k]):
            out.append(Change("attribute", file, f"{var}:{k}", "", _fmt(a[k]), _fmt(b[k])))


def _read(ds, name: str) -> np.ndarray:
    v = np.asarray(ds.variables[name][:])
    return v.reshape(1) if v.ndim == 0 else v


def _numeric(a: np.ndarray) -> bool:
    return a.dtype.kind in "iufb"


def _cell_diffs(name: str, a: np.ndarray, b: np.ndarray) -> list[tuple[tuple, object, object]]:
    if _numeric(a) and _numeric(b):
        af, bf = a.astype(np.float64), b.astype(np.float64)
        equal = (np.isnan(af) & np.isnan(bf)) | (af == bf)
    else:
        equal = a == b
    return [
        (tuple(int(i) for i in ix), a[ix], b[ix])
        for ix in zip(*np.nonzero(~equal), strict=True)
    ]


def compare_file(rel: str, path_a: Path, path_b: Path, res: Result) -> None:
    import netCDF4

    out = res.changes
    with netCDF4.Dataset(str(path_a)) as da, netCDF4.Dataset(str(path_b)) as db:
        da.set_auto_maskandscale(False)
        db.set_auto_maskandscale(False)
        _diff_attrs(rel, GLOBAL, _attrs(da), _attrs(db), out)
        for name in sorted(set(da.variables) | set(db.variables)):
            if name not in db.variables:
                out.append(Change("variable", rel, name, "", "present", "<absent>"))
                continue
            if name not in da.variables:
                out.append(Change("variable", rel, name, "", "<absent>", "present"))
                continue
            _diff_attrs(rel, name, _attrs(da.variables[name]), _attrs(db.variables[name]), out)
            a, b = _read(da, name), _read(db, name)
            res.n_variables_compared += 1
            res.n_cells_compared += int(a.size)
            if a.shape != b.shape:
                out.append(Change("shape", rel, name, "", str(a.shape), str(b.shape)))
                continue
            if a.size == 0:
                continue
            if _numeric(a) and _numeric(b):
                n = a.shape[0]
                ident = np.arange(n)
                join = JoinResult(ident, ident, np.array([], int), np.array([], int), n, n)
                (verdict,) = compare_variables(_Pair(name, a), _Pair(name, b), join, {name: "A"})
                if verdict.n_diff == 0:
                    continue
            for ix, old, new in _cell_diffs(name, a, b):
                out.append(Change("cell", rel, name, str(ix), _fmt(old), _fmt(new)))


def run(old_dir: Path, new_dir: Path) -> Result:
    res = Result()
    old, new = _find_files(old_dir), _find_files(new_dir)
    for rel in sorted(set(old) | set(new)):
        if rel not in new:
            res.changes.append(Change("file", rel, "", "", "present", "<absent>"))
        elif rel not in old:
            res.changes.append(Change("file", rel, "", "", "<absent>", "present"))
        else:
            res.n_files_compared += 1
            try:
                compare_file(rel, old[rel], new[rel], res)
            except Exception as exc:  # an unreadable file is a change, never a skip
                res.changes.append(Change("error", rel, "", "", "", f"{type(exc).__name__}: {exc}"))
    return res


def new_version_section(changes_text: str, version: str | None = None) -> str:
    """The text of the new version's section of the changes file (see the module docstring)."""
    parts = re.split(r"(?m)^(?=## )", changes_text)
    sections = [p for p in parts if p.startswith("## ")]
    if not sections:
        raise ValueError("the changes file has no '## ' section")
    if version is None:
        return sections[0]
    for s in sections:
        if version in s.splitlines()[0]:
            return s
    raise ValueError(f"the changes file has no '## ' section whose heading contains {version!r}")


def is_named(ch: Change, section: str) -> bool:
    if ch.file in section:
        return True
    name = ch.variable.split(":")[-1] if ch.kind == "attribute" else ch.variable
    if name and name != GLOBAL:
        # In backticks only: a bare common word in prose ("time") names nothing.
        return f"`{name}`" in section
    return False


def render(res: Result, old_dir: Path, new_dir: Path, version_heading: str) -> str:
    unnamed = [c for c in res.changes if not c.named]
    lines = [
        "# Changed cells",
        "",
        f"- old: `{old_dir}`",
        f"- new: `{new_dir}`",
        f"- changes-file section used: {version_heading}",
        f"- files compared: {res.n_files_compared}; variables: {res.n_variables_compared}; "
        f"cells: {res.n_cells_compared}",
        f"- changes: {len(res.changes)} ({len(unnamed)} not named in the changes file)",
        "- excluded: the `Creation Time` attribute",
        "",
    ]
    if not res.changes:
        lines += ["No changes.", ""]
        return "\n".join(lines)
    only = [c for c in res.changes if c.kind in ("file", "error")]
    if only:
        lines += ["## Files present on one side only, or unreadable", "",
                  "| file | old | new | named |", "|---|---|---|---|"]
        lines += [f"| {c.file} | {c.old} | {c.new} | {'named' if c.named else 'UNNAMED'} |"
                  for c in only]
        lines.append("")
    rest = [c for c in res.changes if c.kind not in ("file", "error")]
    if rest:
        lines += ["## Changed cells, attributes, variables and shapes", "",
                  "| kind | file | variable | index | old | new | named |",
                  "|---|---|---|---|---|---|---|"]
        for c in rest:
            cells = [c.kind, c.file, c.variable, c.index, c.old, c.new,
                     "named" if c.named else "UNNAMED"]
            lines.append("| " + " | ".join(x.replace("|", "\\|") for x in cells) + " |")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--old-dir", required=True, type=Path)
    ap.add_argument("--new-dir", required=True, type=Path)
    ap.add_argument("--changes", type=Path, default=DEFAULT_CHANGES,
                    help="the release history (default: docs/developer/HISTORY.md)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--version", default=None,
                    help="select the changes file's '## ' section whose heading contains this "
                         "(default: the first section)")
    args = ap.parse_args(argv)
    for d in (args.old_dir, args.new_dir):
        if not d.is_dir():
            print(f"error: not a directory: {d}", file=sys.stderr)
            return 2
    if not args.changes.is_file():
        print(f"error: no such file: {args.changes}", file=sys.stderr)
        return 2
    try:
        section = new_version_section(args.changes.read_text(encoding="utf-8"), args.version)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    res = run(args.old_dir, args.new_dir)
    for c in res.changes:
        c.named = is_named(c, section)
    args.out.write_text(render(res, args.old_dir, args.new_dir, section.splitlines()[0]),
                        encoding="utf-8", newline="\n")
    unnamed = sum(1 for c in res.changes if not c.named)
    print(f"{len(res.changes)} change(s), {unnamed} not named in the changes file; "
          f"wrote {args.out}")
    return 1 if unnamed else 0


if __name__ == "__main__":
    sys.exit(main())
