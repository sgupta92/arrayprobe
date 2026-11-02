# SPDX-License-Identifier: BSD-3-Clause
"""Repair PDF line-wrapping in extracted MATLAB, using Octave's parser as the oracle.

Text extracted from a PDF loses long lines: the renderer wraps them, and the
extractor emits the wrap as a newline. The result is code that reads correctly to
a human and is syntactically invalid::

    DMT_DOF_SPEC_OVERLOAD(arrayIndex+1:...) =
    data(i).DMT_DOF_SPEC_OVERLOAD;                     % dangling '='

    ...,str2doubl
    e(NEWtime2dc(5:6))),...                            % identifier split in two

Both are the same defect and both are repaired by rejoining the two lines.

**Why the parser drives this rather than a heuristic.** The obvious rule -- "join
any line longer than the wrap column" -- does not work, because there is no wrap
column: measured across the staged files, unwrapped lines reach 140 characters
while wrapped ones break at 112. A rule keyed on trailing operators would catch
the first example and miss the second, where the break falls mid-identifier and
leaves both halves looking like ordinary code.

So instead: ask Octave to parse, and if it reports a syntax error at line *N*,
join *N-1* to *N* and ask again. Octave decides what is broken and when it is
fixed; this module only supplies candidate repairs. The loop terminates because
each accepted repair removes a line, and a repair that does not move the error
forward is rejected.

**This is validated on ground truth before it is trusted.** Two staged files have
real counterparts on disk, and ``imgProc_sm`` is one of them -- so the repairer
can be run on its extraction and the result compared against the file MATLAB
actually ran. See ``test_dewrap_reconstructs_imgproc`` in
``tests/test_dissertation_recovery.py``: the repaired extraction must match the
real source once whitespace is normalised. A repairer proven on a file where the
answer is known is worth considerably more than one argued about.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

__all__ = ["OctaveUnavailable", "octave_binary", "parse_status", "dewrap"]

#: Octave reports these when the file is syntactically fine but is a *script*,
#: so the question "how many input arguments?" does not apply. Not a failure.
_SCRIPT_MARKERS = ("script objects", "user-defined script")

_SYNTAX_RE = re.compile(r"syntax error near line (\d+)", re.I)

#: Repairs are bounded: a file needing more than this is not wrap damage, it is
#: something that wants a human.
MAX_REPAIRS = 60


class OctaveUnavailable(RuntimeError):
    """Octave is not installed, so the parser oracle cannot run."""


def octave_binary() -> str:
    """Locate ``octave-cli``, preferring PATH and falling back to the winget path."""
    found = shutil.which("octave-cli") or shutil.which("octave")
    if found:
        return found
    candidate = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Programs" / "GNU Octave" / "Octave-11.3.0" / "mingw64" / "bin" / "octave-cli.exe"
    )
    if candidate.exists():
        return str(candidate)
    raise OctaveUnavailable(
        "octave-cli not found on PATH. Install with `winget install GNU.Octave` "
        "(note: the id is GNU.Octave, not GNU.Octave.GNU.Octave)."
    )


def parse_status(text: str, stem: str, octave: str | None = None) -> tuple[bool, int | None, str]:
    """Ask Octave to parse ``text`` as ``<stem>.m``.

    Returns ``(ok, error_line, message)``. ``error_line`` is 1-based and only set
    for a syntax error.
    """
    octave = octave or octave_binary()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{stem}.m"
        path.write_text(text, encoding="utf-8", newline="\n")
        # nargin() forces a full parse and compile of the function body. For a
        # script it raises a *specific* complaint that means "parsed fine, wrong
        # question", which is why that message is whitelisted rather than
        # treated as failure.
        script = (
            f"addpath('{tmp.replace(chr(92), '/')}');"
            f"try, nargin('{stem}'); printf('PARSE_OK\\n');"
            f"catch e, printf('PARSE_ERR %s\\n', e.message); end"
        )
        proc = subprocess.run(
            [octave, "--no-gui", "--quiet", "--eval", script],
            capture_output=True, text=True, timeout=180,
        )
    out = proc.stdout + proc.stderr
    if "PARSE_OK" in out:
        return True, None, "parsed (function)"
    if any(m in out for m in _SCRIPT_MARKERS):
        return True, None, "parsed (script)"
    m = _SYNTAX_RE.search(out)
    if m:
        detail = out.strip().splitlines()[-1] if out.strip() else "syntax error"
        return False, int(m.group(1)), detail
    return False, None, out.strip()[-300:] or "unknown parse failure"


def dewrap(text: str, stem: str, octave: str | None = None):
    """Rejoin PDF-wrapped lines until Octave parses the file.

    Returns ``(repaired_text, repairs)`` where ``repairs`` lists
    ``(line_number, joined_text)`` for each accepted join, so every change this
    makes is reportable rather than silent.
    """
    octave = octave or octave_binary()
    lines = text.split("\n")
    repairs: list[tuple[int, str]] = []
    seen: set[int] = set()

    for _ in range(MAX_REPAIRS):
        ok, line_no, message = parse_status("\n".join(lines), stem, octave)
        if ok:
            return "\n".join(lines), repairs
        if line_no is None:
            raise ValueError(f"{stem}: parse failed without a line number: {message}")

        idx = line_no - 1                      # 0-based index of the continuation
        if idx <= 0 or idx >= len(lines):
            raise ValueError(f"{stem}: syntax error at line {line_no}, outside the file")

        # The continuation is the reported line; its head is the line above.
        # Guard against looping on a line we already tried.
        if idx in seen:
            raise ValueError(
                f"{stem}: joining line {line_no} did not clear the error "
                f"(the damage is not simple wrapping): {message}"
            )
        seen.add(idx)

        joined = lines[idx - 1].rstrip() + lines[idx].lstrip()
        lines[idx - 1:idx + 1] = [joined]
        repairs.append((line_no, joined.strip()[:120]))

    raise ValueError(f"{stem}: still not parsing after {MAX_REPAIRS} repairs")
