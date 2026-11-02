# SPDX-License-Identifier: BSD-3-Clause
"""Rewrite machine-local absolute path prefixes to fixed tokens, keeping every basename.

WHY. An oracle bank or a run records the paths it was given: a netCDF ``Image Source`` or
``Data Source`` attribute names its input, a JSON golden stores a ``src_dir``, and captured
Octave or GDL stderr names a temporary ``bank.m``. Written on a developer machine, each of those
carries a home directory into a shipped fixture (``tests/test_no_personal_paths.py``).
Regenerating does not help, because every machine writes its own paths again, so the prefix is
scrubbed at write time and the recorded values stay what the oracle wrote.

TOKENS. The convention of the notebook scrubber
(``scripts/execute_example_notebooks.py::scrub_local_paths``), whose primitives this module
defines and that tool imports: this interpreter becomes ``python``, a temporary directory
(with its ``tmp*`` mkdtemp child) ``<tmp>``, the repository ``<repo>`` and a home directory ``~``.
Two additions for
recorded output: a repository checkout at ``<home>/Projects/arrayprobe``, including an agent
worktree nested inside that checkout, is ``<repo>`` on any machine; and a JSON-escaped
spelling (doubled backslashes) is rewritten like the plain one. A placeholder user (``x``,
``...``, ``<user>``) is left alone, as the detector leaves it.

Only prefixes change: a basename, a line number or a message around a path is untouched, so a
test that compares basenames or error substrings reads the same value before and after.

Usage, from the repository root::

    .venv/Scripts/python.exe scripts/scrub_paths.py --check FILE...   # exit 1 if any would change
    .venv/Scripts/python.exe scripts/scrub_paths.py --apply FILE...   # rewrite text files in place

GENERATORS CALL :func:`scrub_output` on what they write into ``tests/data`` (a file or a
directory of them), after the oracle has written it: a netCDF global string attribute, a JSON
string value (dumped back in the file's own format) or a text line is rewritten; anything else
is left alone, and a file with nothing to scrub is not opened for writing.
``tests/test_generators_scrub_paths.py`` checks the call is present in every generator that
has written a path into a fixture.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent


def _spellings(path: str | Path) -> list[str]:
    """Every way ``path`` is likely to appear in captured text, longest first.

    Both separators, and both the path as given and its resolved long form (on
    Windows ``tempfile.gettempdir()`` can be an 8.3 short name while
    ``resolve()`` expands it).
    """
    out: set[str] = set()
    for form in {str(path), str(Path(path).resolve())}:
        form = form.rstrip("\\/")
        if len(form) > 3:  # never rewrite a bare drive root
            out.update({form, form.replace("\\", "/"), form.replace("/", "\\")})
    return sorted(out, key=len, reverse=True)


#: A ``tempfile.mkdtemp`` child: ``tmp`` plus a random suffix.
_MKDTEMP_CHILD = r"(?:[\\/]+tmp[A-Za-z0-9_]+)?"

#: Temporary-directory shapes left once the home directory has become ``~``,
#: plus the POSIX ones: a Windows user temp dir, ``/tmp`` and macOS's per-user
#: ``/var/folders/.../T``, each optionally followed by a mkdtemp child.
_GENERIC_TMP = re.compile(
    r"(?:~[\\/]+AppData[\\/]+Local[\\/]+Temp"
    r"|(?<![\w.~])/tmp"
    r"|(?<![\w.~])/(?:private/)?var/folders/[^\s\\/]+/[^\s\\/]+/T)"
    + _MKDTEMP_CHILD)

#: Stand-ins for a user name that name nobody (``tests/test_no_personal_paths.py``).
PLACEHOLDER_USERS = frozenset({"x", "..."})

#: One or more separators, including JSON's escaped backslash.
_SEP = r"(?:\\\\|\\|/)+"
_HOME_PREFIX = (r"(?:[A-Za-z]:" + _SEP + r"Users|(?<![\w.])/[A-Za-z]/Users"
                r"|(?<![\w.])/(?:home|Users))")
_USER = r"(?P<user>[^\\/\s\"'`<>:*?|,;()\[\]{}]+)"

#: A home directory spelled out, on any machine: the detector's shape.
_GENERIC_HOME = re.compile(_HOME_PREFIX + _SEP + _USER, re.IGNORECASE)

#: A checkout of this repository under a home directory, or an agent worktree inside one.
_GENERIC_REPO = re.compile(
    _HOME_PREFIX + _SEP + _USER + _SEP + r"Projects" + _SEP + r"arrayprobe"
    + r"(?:" + _SEP + r"\.claude" + _SEP + r"worktrees" + _SEP + r"[^\\/\s\"'<>:*?|;]+)?"
    + r"(?![\w.-])", re.IGNORECASE)


#: A Windows 8.3 short name used as a directory (a user folder printed short, as a temporary
#: directory usually is): ``<NAME>~1.<EXT>\AppData``. Its home prefix may already be gone.
_SHORT_DIR = re.compile(r"(?<![\w~])[A-Za-z0-9]{1,6}~[0-9]\.[A-Za-z0-9]{1,3}(?=" + _SEP + r")")


def _all_spellings(path: str | Path) -> list[str]:
    """:func:`_spellings` plus each backslash form as JSON escapes it, longest first."""
    out = set(_spellings(path))
    out.update(s.replace("\\", "\\\\") for s in list(out) if "\\" in s)
    return sorted(out, key=len, reverse=True)


def _unless_placeholder(token: str):
    def sub(m: re.Match) -> str:
        return m.group(0) if m.group("user").lower() in PLACEHOLDER_USERS else token
    return sub


def scrub_text(text: str) -> str:
    """Replace machine-local path prefixes in ``text`` with tokens (module docstring).

    Most specific first: the interpreter and the temporary directory usually sit inside the
    home directory, and the repository may too. Idempotent.
    """
    for s in _all_spellings(sys.executable):
        text = text.replace(s, "python")
    for s in _all_spellings(tempfile.gettempdir()):
        text = re.sub(re.escape(s) + r"(?!\w)" + _MKDTEMP_CHILD, "<tmp>", text)
    for s in _all_spellings(REPO_ROOT):
        text = re.sub(re.escape(s) + r"(?![\w.-])", "<repo>", text)
    text = _GENERIC_REPO.sub(_unless_placeholder("<repo>"), text)
    for s in _all_spellings(Path.home()):
        text = re.sub(re.escape(s) + r"(?![\w.-])", "~", text)
    text = _GENERIC_HOME.sub(_unless_placeholder("~"), text)
    text = _SHORT_DIR.sub("~", text)
    return _GENERIC_TMP.sub("<tmp>", text)


#: What :func:`scrub_output` rewrites, by suffix; any other file is left as written.
NETCDF_SUFFIXES = frozenset({".nc", ".cdf"})
TEXT_SUFFIXES = frozenset({".json", ".log", ".txt", ".csv"})


# --------------------------------------------------------------------------- file formats

def _walk(obj, fn):
    if isinstance(obj, dict):
        return {k: _walk(v, fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(v, fn) for v in obj]
    return fn(obj) if isinstance(obj, str) else obj


def _json_formats():
    for indent in (None, 1, 2, 4):
        for seps in (None, (",", ":"), (", ", ": "), (",", ": ")):
            for ensure_ascii in (True, False):
                for sort_keys in (False, True):
                    for tail in ("\n", ""):
                        yield dict(indent=indent, separators=seps, ensure_ascii=ensure_ascii,
                                   sort_keys=sort_keys), tail


def _dump(obj, fmt, tail, crlf):
    text = json.dumps(obj, **fmt) + tail
    return text.replace("\n", "\r\n") if crlf else text


def _scrub_json_text(raw: str) -> tuple[str, str]:
    """(scrubbed text, method): string leaves rewritten, dumped in the file's own format.

    The format (indent, separators, ``ensure_ascii``, key order, trailing newline, line
    ending) is the one whose dump of the *unscrubbed* object reproduces ``raw``; when none
    does, the raw text is scrubbed instead.
    """
    obj = json.loads(raw)
    crlf = "\r\n" in raw
    for fmt, tail in _json_formats():
        if _dump(obj, fmt, tail, crlf) == raw:
            return _dump(_walk(obj, scrub_text), fmt, tail, crlf), "structured"
    return scrub_text(raw), "raw-text"


def _scrub_netcdf(path: Path) -> list[str]:
    """Rewrite the global string attributes whose value changes; return their names.

    NETCDF3 keeps attribute order in place. In NETCDF4 (HDF5) a rewritten attribute moves to
    the end of the creation order, so the first changed attribute and every one after it are
    deleted and re-added in their original order; the order is then asserted.
    """
    import netCDF4
    with netCDF4.Dataset(path) as ds:  # read-only first: a clean file is never opened to write
        names = list(ds.ncattrs())
        values = {n: ds.getncattr(n) for n in names}
    new = {n: scrub_text(v) for n, v in values.items()
           if isinstance(v, str) and scrub_text(v) != v}
    if not new:
        return []
    with netCDF4.Dataset(path, "a") as ds:
        if ds.data_model.startswith("NETCDF4"):
            tail = names[min(names.index(n) for n in new):]
            for n in tail:
                ds.delncattr(n)
            for n in tail:
                ds.setncattr(n, new.get(n, values[n]))
        else:
            for n, v in new.items():
                ds.setncattr(n, v)
    with netCDF4.Dataset(path) as ds:
        if list(ds.ncattrs()) != names:
            raise AssertionError(f"{path}: global attribute order changed: {ds.ncattrs()}")
    return sorted(new)


def _scrub_file(path: Path) -> str:
    """Scrub one file in place; return a one-line description of what changed."""
    if path.suffix in NETCDF_SUFFIXES:
        names = _scrub_netcdf(path)
        return f"netCDF attributes {names}" if names else ""
    raw = path.read_bytes().decode("utf-8", "surrogateescape")
    if path.suffix == ".json":
        new, method = _scrub_json_text(raw)
    else:
        new, method = scrub_text(raw), "raw-text"
    if new == raw:
        return ""
    path.write_bytes(new.encode("utf-8", "surrogateescape"))
    return f"{method} rewrite"


def scrub_output(*paths: str | Path) -> list[Path]:
    """Scrub each generator output in place (a file, or every file under a directory).

    Returns the files that changed. A missing path is skipped: a generator run with a subset
    of its cases writes only some of its outputs.
    """
    changed = []
    for root in map(Path, paths):
        files = sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else [root]
        for f in files:
            if f.is_file() and f.suffix in NETCDF_SUFFIXES | TEXT_SUFFIXES \
                    and _scrub_file(f):
                changed.append(f)
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="exit 1 if any file would change")
    mode.add_argument("--apply", action="store_true", help="rewrite text files in place")
    ap.add_argument("files", nargs="+", type=Path)
    args = ap.parse_args(argv)
    changed = []
    for path in args.files:
        # Bytes, not read_text: line endings and any undecodable byte survive unchanged.
        text = path.read_bytes().decode("utf-8", "surrogateescape")
        new = scrub_text(text)
        if new != text:
            changed.append(path)
            if args.apply:
                path.write_bytes(new.encode("utf-8", "surrogateescape"))
    for path in changed:
        print(f"{'scrubbed' if args.apply else 'would scrub'}: {path}")
    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    sys.exit(main())
