# SPDX-License-Identifier: BSD-3-Clause
"""Find GDL and run a ``.pro`` script against the vendored SODA-2 tree.

Mirrors ``octave_oracle/dewrap.py``'s locator convention: prefer PATH, fall back
to the one known install path on this machine, and raise with the exact command
that installs it rather than returning something falsy.

GDL is **not** available from winget or conda-forge on Windows (both checked
2026-09-11: winget has only unrelated ``GDLauncher``/``GOGDL``; conda-forge's
``gdl`` has no win-64 build, and ``hgdl`` is a different package entirely). The
Windows build is a portable tree published as a GitHub release asset. There is
no installer to run and nothing is written outside the unpacked directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import _upstream  # noqa: E402

#: Where this machine's portable GDL tree was unpacked. Not a repository path:
#: GDL is a tool, like Octave, and lives outside the project the way Octave does.
DEFAULT_GDL = Path(os.environ.get("USERPROFILE", "")) / "tools" / "gdl" / "bin" / "gdl.exe"

#: The vendored SODA-2 source, added to ``!path`` for every oracle run.
SODA2_TREE = _upstream.source("soda2")

#: GDL chatter that is not an error. The DLM line is the dynamically-loadable-module
#: registry, which this portable tree does not ship and no SODA-2 routine uses; the
#: "Compiled module" lines are GDL announcing each routine it resolved off the path,
#: which is exactly what the oracle wants it to do. Both go to stderr, so they are
#: filtered here and a caller's "did it complain?" check is about its own script.
_NOISE_EXACT = (
    "% Attempt to call undefined procedure: DLM_REGISTER",
    "% Execution halted at: $MAIN$",
)
_NOISE_PREFIX = ("% Compiled module:",)


def _is_noise(line: str) -> bool:
    stripped = line.rstrip()
    return stripped in _NOISE_EXACT or stripped.startswith(_NOISE_PREFIX)


class GDLUnavailable(RuntimeError):
    """GDL is not installed, so the SODA-2 oracle cannot run."""


def idl_double(value: float) -> str:
    """``value`` as an IDL **double** literal.

    Two traps, both met the hard way and both silent-ish, so this exists once
    rather than in each bank:

    1. A bare decimal literal in IDL is **FLOAT**, not double. Writing
       ``double([0.0, 0.001])`` widens values that have already been rounded to
       single precision, so an oracle bank ends up giving GDL different inputs
       from the ones it gives the port -- which means it is not comparing
       implementations at all. That happened to the first `princomp` bank and
       looked like a porting defect (`sxx` = 2.00000019e-6 against an exact
       2e-6, float32 epsilon).
    2. ``d`` is IDL's **exponent marker**, not a suffix. ``1.0d-9`` is a double;
       ``1e-09d`` is a *syntax error*. Appending ``d`` works only for values
       Python formats without an exponent, so a bank can pass for a long time
       and then fail the moment someone adds a small or large case -- which is
       exactly how the angles bank met it, on ``1e-9``.

    The mantissa keeps ``.17g``'s full precision so the literal round-trips to
    the same double Python holds -- shortening it would reintroduce trap 1 in a
    quieter form.

    >>> idl_double(0.001)
    '0.001d'
    >>> idl_double(1e-09)
    '1.0000000000000001d-09'
    >>> idl_double(-2.5e20)
    '-2.5d+20'
    """
    text = f"{float(value):.17g}"
    if "e" in text or "E" in text:
        mantissa, _, exponent = text.replace("E", "e").partition("e")
        return f"{mantissa}d{exponent}"
    return text + "d"


def gdl_binary() -> str:
    """Locate ``gdl``, preferring PATH and falling back to the portable install."""
    found = shutil.which("gdl")
    if found:
        return found
    if DEFAULT_GDL.exists():
        return str(DEFAULT_GDL)
    raise GDLUnavailable(
        f"gdl not found on PATH or at {DEFAULT_GDL}. There is no winget or conda-forge "
        "package for Windows; download the portable tree with\n"
        "  gh release download weekly-release --repo gnudatalanguage/gdl "
        '--pattern "gdl-Windows-x86_64-standard.zip"\n'
        "and unzip it to %USERPROFILE%\\tools\\gdl (it contains bin/, lib/, share/ — "
        "no installer, no elevation)."
    )


_SENTINEL = "__RUN_PRO_DONE__"


def run_pro(
    script: str,
    *,
    gdl: str | None = None,
    timeout: int = 300,
    extra_files: dict[str, str] | None = None,
    sentinel_exit: bool = False,
    tree: Path | None = None,
) -> tuple[str, str]:
    """Compile ``script`` as a procedure body and run it, SODA-2 on the path.

    The body is wrapped in ``pro bank ... end`` and compiled, rather than run as
    a batch file. IDL — and GDL with it — executes a batch file one *line* at a
    time, so a multi-line ``for ... do begin ... endfor`` in batch form is a
    syntax error on the ``begin`` line; only a compiled procedure takes blocks.
    The temporary directory holding ``bank.pro`` is put on ``GDL_PATH`` ahead of
    the SODA-2 tree, so nothing is written into the vendored source.

    ``extra_files`` writes additional named files (e.g. ``{"erode.pro": ...}``)
    into that same temporary directory, ahead of the vendored tree on
    ``GDL_PATH`` -- a caller's shim for a routine GDL itself lacks. Nothing is
    ever written into ``SODA2/``.

    On this machine's GDL 1.1.2 Windows build, ``<IDL_DEFAULT>`` in
    ``GDL_PATH`` expands to nothing -- there is no library directory on
    ``!PATH`` -- so any GDL *library* routine (``INTERPOL``, ``STRSPLIT``,
    ...; anything under ``share/gnudatalanguage/lib/``, as opposed to a
    true built-in) is undefined unless supplied through ``extra_files``,
    verbatim from the install (measured 2026-09-14,
    ``probe_pthdat_hang.py``; every bank's startup ``Attempt to call
    undefined procedure: DLM_REGISTER`` stderr line is this same defect).

    ``sentinel_exit`` works around a measured GDL 1.1.2 Windows defect (September
    2026): any ``ncdf_*``
    call, create or read-only open, makes the process deadlock in kernel-side
    teardown *after* it has run to completion and flushed stdout -- so a script
    that finished correctly still never returns from ``subprocess.run``. With
    this flag, a sentinel print is appended after the script body, stdout is
    read incrementally from a pipe on a background thread, and the process is
    killed as soon as the sentinel line is seen (or on timeout, or on its own
    exit) rather than waited on to exit by itself; measured on this build, a
    process killed this way after ``proc.kill()`` leaves no lingering ``gdl.exe``
    when launched from Python with pipes, unlike a PowerShell-launched one.
    ``sentinel_exit=False`` (the default) is unchanged, byte-for-byte, from
    before this parameter existed.

    ``tree`` selects which SODA-2 source tree goes on ``GDL_PATH``, defaulting to
    ``SODA2_TREE`` (the vendored ``afcea15``, unchanged behaviour when the
    keyword is absent). Pass a different tree (e.g. the ``3ded679`` 2016
    revision) to run against it instead -- and *only* it: the default tree is
    never added alongside a given one, so a routine missing from the given tree
    halts with an undefined-procedure error rather than silently falling
    through to ``afcea15``.

    Returns ``(stdout, stderr)`` with GDL's own startup noise removed from stderr.
    """
    binary = gdl or gdl_binary()
    active_tree = tree if tree is not None else SODA2_TREE
    if not active_tree.is_dir():
        raise GDLUnavailable(f"vendored SODA-2 tree not found at {active_tree}")
    with tempfile.TemporaryDirectory() as tmp:
        body = script.rstrip()
        if sentinel_exit:
            body = body + f"\nprint, '{_SENTINEL}'"
        (Path(tmp) / "bank.pro").write_text(
            "pro bank\n" + body + "\nend\n", encoding="utf-8"
        )
        for name, contents in (extra_files or {}).items():
            (Path(tmp) / name).write_text(contents, encoding="utf-8")
        env = {
            **os.environ,
            "GDL_STARTUP": "",
            "GDL_PATH": os.pathsep.join([tmp, str(active_tree), "<IDL_DEFAULT>"]),
        }
        if not sentinel_exit:
            proc = subprocess.run(  # noqa: S603 - fixed binary, generated script
                [binary, "-quiet", "-e", "bank"],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            stdout, stderr = proc.stdout, proc.stderr
        else:
            stdout, stderr = _run_pro_sentinel(binary, env, timeout)
    noise = "\n".join(line for line in stderr.splitlines() if not _is_noise(line))
    return stdout, noise


def _run_pro_sentinel(binary: str, env: dict[str, str], timeout: int) -> tuple[str, str]:
    """Launch ``bank`` with pipes, killing the process on sentinel/exit/timeout."""
    proc = subprocess.Popen(  # noqa: S603 - fixed binary, generated script
        [binary, "-quiet", "-e", "bank"],
        # A GDL halt (an error anywhere under ``bank``, which a CATCH in
        # ``bank`` does not see in GDL 1.1.2 when it is raised in a called
        # procedure) drops to the interpreter prompt; with stdin at EOF the
        # prompt exits at once instead of waiting until the timeout
        # (measured: 900 s on the PBP driver bank's frame_images case).
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    out_lines: list[str] = []
    err_lines: list[str] = []

    def _read(stream, sink):
        for line in stream:
            sink.append(line)

    out_thread = threading.Thread(target=_read, args=(proc.stdout, out_lines))
    err_thread = threading.Thread(target=_read, args=(proc.stderr, err_lines))
    out_thread.daemon = True
    err_thread.daemon = True
    out_thread.start()
    err_thread.start()

    start = time.monotonic()
    saw_sentinel = False
    exited = False
    while True:
        if any(_SENTINEL in line for line in out_lines):
            saw_sentinel = True
            break
        if proc.poll() is not None:
            exited = True
            break
        if time.monotonic() - start > timeout:
            break
        time.sleep(0.25)

    if saw_sentinel or not exited:
        proc.kill()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
    out_thread.join(timeout=5)
    err_thread.join(timeout=5)
    if proc.stdout is not None:
        proc.stdout.close()
    if proc.stderr is not None:
        proc.stderr.close()

    stdout = "".join(out_lines)
    stderr = "".join(err_lines)
    if saw_sentinel:
        stdout = "".join(line for line in out_lines if _SENTINEL not in line)
        return stdout, stderr
    if exited:
        return stdout, stderr
    raise subprocess.TimeoutExpired(
        [binary, "-quiet", "-e", "bank"], timeout, output=stdout, stderr=stderr
    )
