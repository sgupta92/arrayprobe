# SPDX-License-Identifier: BSD-3-Clause
"""One cleanup for every test that launches a detached run.

**Why it exists (2026-10-01).** Tests of the launcher left processes behind:
``_detached_wrapper.sh dead_canary false`` and its wakelock ``powershell.exe``
were alive 2.5 h after the run that launched them. Each test had its own
cleanup, or none, and the one that existed killed the wrapper by Windows pid
with ``taskkill /T``, which cannot reach a process whose parent has already
exited (the MSYS fork stub that owns a native child outlives its parent). A
test that pointed the launcher at the real ``run_logs/`` also left its log
there: it unlinked the log at once, and the launcher's tree-fingerprint
watcher (``sh -c "while kill -0 ..."``, up to 20 s later) recreated it.

**How.** Every launch gets a unique name from :func:`canary_name`. Every
process whose command line carries that token -- the wrapper, its fork stubs,
the watcher (its command line holds the log path) -- is a root, and every
process descended from a root is in the tree (the wakelock powershell, the
wrapped command, ``sleep``). :func:`reap` kills each with
``taskkill /PID <winpid> /T /F`` and asserts that none survives. It reads the
Windows process table (``Win32_Process``), because MSYS ``ps`` does not list
native grandchildren.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid

ISSUED: list[str] = []


def canary_name(base: str) -> str:
    """A launch name no other run on the machine carries; registered for the guard."""
    name = f"{base}_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    ISSUED.append(name)
    return name


def _process_table() -> list[tuple[int, int, str]]:
    if sys.platform != "win32":
        return []
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "Get-CimInstance Win32_Process | Select-Object ProcessId,"
         "ParentProcessId,CommandLine | ConvertTo-Json -Compress"],
        capture_output=True, text=True, timeout=120).stdout
    # strict=False: a live command line can carry a raw control character, which
    # ConvertTo-Json passes through unescaped (suite_1002e, char 176924).
    rows = json.loads(out or "[]", strict=False)
    if isinstance(rows, dict):
        rows = [rows]
    return [(int(r["ProcessId"]), int(r["ParentProcessId"]),
             r.get("CommandLine") or "") for r in rows]


def tree_of(token: str, table: list[tuple[int, int, str]] | None = None
            ) -> list[tuple[int, str]]:
    """Every live process carrying ``token`` and everything descended from one."""
    table = _process_table() if table is None else table
    me = os.getpid()
    found = {pid for pid, _, cmd in table if token in cmd and pid != me}
    grew = True
    while grew:
        grew = False
        for pid, ppid, _ in table:
            if ppid in found and pid not in found:
                found.add(pid)
                grew = True
    return [(pid, cmd) for pid, _, cmd in table if pid in found]


def reap(token: str, timeout_s: float = 15.0) -> None:
    """Kill every process of the launch named ``token`` and assert none survives."""
    if sys.platform != "win32":
        return
    deadline = time.time() + timeout_s
    left = tree_of(token)
    while left and time.time() < deadline:
        for pid, _ in left:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True)
        time.sleep(0.5)
        left = tree_of(token)
    if left:
        raise AssertionError(
            f"launch {token!r} left {len(left)} process(es) alive after "
            "taskkill /T /F: " + "; ".join(f"{p}: {c[:120]}" for p, c in left))
