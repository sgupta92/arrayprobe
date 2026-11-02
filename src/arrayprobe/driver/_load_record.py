# SPDX-License-Identifier: BSD-3-Clause
"""What else the machine was doing while a timing ran.

The rule: *a wall-clock figure is quotable only from a run whose harness recorded
the machine's other processes and load while it ran.* The incident behind it
: a 1.22x speed-up was withdrawn after its timed arms were found
to have run beside the full test suite -- 913.4 s against 168.2 s for the same
configuration -- and nothing the harness wrote could show it.

``LoadRecorder`` is a context manager a timing harness wraps its timed window
in. It samples every process on the machine at entry, every ``interval``
seconds (default 60) from a daemon thread, and at exit, and records for each *other*
process (not this one, and by default not its descendants, which are the work
being timed) the CPU seconds it used inside the window. At exit it writes the
record as JSON (``path``) and prints one line::

    LOAD RECORD: CLEAN|CONTAMINATED|UNRECORDED -- <why> (<path>)

**Threshold.** CONTAMINATED when any single other process averaged at least
``PROCESS_CORE_LIMIT`` (0.25) of a core over the window, or all other
processes together at least ``TOTAL_CORE_LIMIT`` (1.0) core. That incident's
contaminant was a full test suite, which holds one core or more for its whole
run; a quarter core sustained over a window is well above an idle desktop's
background (antivirus, browser tabs) yet catches a competing python, Octave or
GDL run long before it can move a figure by 1.22x. The limits are recorded in
the JSON so a reader can re-judge from the per-process table.

**Cost.** One snapshot reads every process's CPU times, measured at about
3.3 s of CPU on this Windows machine (531 processes, 2026-09-24), almost all
of it psutil's fallback for processes it may not open. At the default 60 s
interval that is ~0.06 core of load the recorder itself adds; it is this
process, so it is excluded from its own record, and it is stated here so a
reader can weigh it.

Needs ``psutil`` (in the venv). Without it the record says UNRECORDED and the
timing is not quotable under that rule -- the recorder never pretends.

**It never fails the run it wraps.** Any error while sampling or writing is
caught and the record says UNRECORDED with the reason; the timed work carries
on. ``enabled=False`` makes it a no-op that writes and prints nothing, for a
process that is itself a worker of a recorded parent (``run_flight.py --jobs``).
``run_flight.py`` also passes ``enabled=False`` when the environment sets
``ARRAYPROBE_LOAD_RECORD=off``: set only by ``make_demo_reference.py``'s v3.5 demo build,
whose time is a budget and never a quoted figure. A run with it off is not quotable.
"""

from __future__ import annotations

import json
import os
import struct
import threading
import time
from pathlib import Path

try:  # pragma: no cover - exercised by whichever branch the venv has
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

PROCESS_CORE_LIMIT = 0.25
TOTAL_CORE_LIMIT = 1.0
NOTABLE_CORE = 0.02  # processes below this average are summarised, not listed
# Windows kernel pseudo-processes: recorded (``kernel_avg_cores``) but kept out
# of the verdict. On the author's machine "System" (pid 4) alone averaged
# 1.87 core over a quiet 5 s with nothing launched (measured 2026-09-24), so
# judging it would call every run CONTAMINATED and the verdict would mean nothing.
KERNEL = {"System", "Registry", "Memory Compression", "Secure System"}


# FILETIME (100 ns ticks since 1601-01-01) to seconds since the Unix epoch,
# the constant psutil's C extension uses for the same conversion.
_EPOCH_AS_FILETIME = 116444736000000000
_SYSTEM_PROCESS_INFORMATION = 5
_STATUS_INFO_LENGTH_MISMATCH = 0xC0000004


def _table_snapshot_windows(
        exclude: set[int]) -> dict[tuple[int, float], tuple[str, float]]:
    """Read the whole process table once through ``NtQuerySystemInformation``.

    psutil's Windows fallback for a process it may not open re-reads this
    same table once per such process (~200 per snapshot, ~2-3 s); this reads
    it once. Fields and units match psutil's: create time as FILETIME
    converted to Unix seconds, user + kernel time in 100 ns units / 1e7, and
    the image name. Layout offsets are those of 64-bit Windows; any other
    layout raises, and the caller falls back to psutil.
    """
    import ctypes
    import sys
    if sys.platform != "win32":  # also what lets mypy check WinDLL off Windows
        raise OSError("table snapshot needs Windows")
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        raise OSError("table snapshot needs 64-bit Windows")
    ntdll = ctypes.WinDLL("ntdll")
    fn = ntdll.NtQuerySystemInformation
    fn.restype = ctypes.c_ulong
    fn.argtypes = [ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
                   ctypes.POINTER(ctypes.c_ulong)]
    size = 1 << 20
    for _ in range(8):
        buf = ctypes.create_string_buffer(size)
        need = ctypes.c_ulong(0)
        status = fn(_SYSTEM_PROCESS_INFORMATION, buf, size, ctypes.byref(need))
        if status == _STATUS_INFO_LENGTH_MISMATCH:
            size = max(size * 2, need.value + (64 << 10))
            continue
        if status != 0:
            raise OSError(f"NtQuerySystemInformation status 0x{status:08X}")
        break
    else:
        raise OSError("NtQuerySystemInformation: buffer never large enough")
    base = ctypes.addressof(buf)
    raw = buf.raw
    out: dict[tuple[int, float], tuple[str, float]] = {}
    off = 0
    while True:
        nxt = struct.unpack_from("<I", raw, off)[0]
        create, user, kernel = struct.unpack_from("<qqq", raw, off + 32)
        name_len, _maxlen, name_ptr = struct.unpack_from("<HH4xQ", raw, off + 56)
        pid = struct.unpack_from("<Q", raw, off + 80)[0]
        if pid != 0 and pid not in exclude:
            if pid == 4:
                name = "System"
            elif name_len and name_ptr:
                if not base <= name_ptr < base + len(raw):
                    raise OSError("image name points outside the table buffer")
                name = ctypes.wstring_at(name_ptr, name_len // 2)
            else:
                name = "?"
            # psutil reports pid 4's create time as 0.0; match it so the key
            # is the same whichever path took the snapshot.
            ct = ((create - _EPOCH_AS_FILETIME) / 10000000.0
                  if create and pid != 4 else 0.0)
            out[(pid, ct)] = (name or "?", (user + kernel) / 10000000.0)
        if nxt == 0:
            return out
        off += nxt


def _snapshot(exclude: set[int]) -> dict[tuple[int, float], tuple[str, float]]:
    if os.name == "nt":
        try:
            return _table_snapshot_windows(exclude)
        except (OSError, ValueError, struct.error):
            pass  # fall back to psutil
    return _psutil_snapshot(exclude)


def _psutil_snapshot(
        exclude: set[int]) -> dict[tuple[int, float], tuple[str, float]]:
    out: dict[tuple[int, float], tuple[str, float]] = {}
    for p in psutil.process_iter(["pid", "name", "create_time", "cpu_times"]):
        info = p.info
        # pid 0 is the "System Idle Process" on Windows: its CPU time is idle time.
        if info["pid"] in exclude or info["pid"] == 0 or info["cpu_times"] is None:
            continue
        ct = info["cpu_times"]
        out[(info["pid"], info["create_time"] or 0.0)] = (
            info["name"] or "?", float(ct.user + ct.system))
    return out


class LoadRecorder:
    """Record other processes' CPU use across a timed window; see module doc."""

    def __init__(self, path, *, interval: float = 60.0,
                 exclude_descendants: bool = True, label: str = "",
                 enabled: bool = True):
        self.path = Path(path)
        self.enabled = enabled
        self._error: str | None = None
        self._thread: threading.Thread | None = None
        self.interval = interval
        self.exclude_descendants = exclude_descendants
        self.label = label
        self.record: dict = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._first: dict = {}
        self._last: dict = {}
        self._samples: list[dict] = []

    # -- sampling -----------------------------------------------------------
    def _exclude(self) -> set[int]:
        me = psutil.Process(os.getpid())
        ex = {me.pid}
        if self.exclude_descendants:
            try:
                ex |= {c.pid for c in me.children(recursive=True)}
            except psutil.Error:
                pass
        return ex

    def _sample(self, first: bool = False) -> None:
        snap = _snapshot(self._exclude())
        with self._lock:
            for key, (name, cpu) in snap.items():
                if key not in self._first:
                    # Present at entry: its baseline is its CPU then. Born later:
                    # everything it used was used inside the window.
                    self._first[key] = (name, cpu if first else 0.0)
                self._last[key] = (name, cpu)
            load = None
            if hasattr(psutil, "getloadavg"):
                try:
                    load = psutil.getloadavg()[0]
                except (OSError, psutil.Error):
                    load = None
            self._samples.append({
                "t": round(time.time(), 1),
                "cpu_percent": psutil.cpu_percent(interval=None),
                "loadavg_1min": load,
                "n_processes": len(snap),
            })

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self._sample()
            except Exception:  # noqa: BLE001 - a sampler must never kill the timed run
                pass

    # -- context ------------------------------------------------------------
    def __enter__(self):
        self._t0 = time.time()
        self._p0 = time.perf_counter()
        if psutil is None or not self.enabled:
            return self
        try:
            psutil.cpu_percent(interval=None)  # prime the system-wide counter
            self._span0 = time.perf_counter()
            self._sample(first=True)
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        except Exception as e:  # noqa: BLE001 - never fail the wrapped run
            self._error = f"entry snapshot failed: {type(e).__name__}: {e}"
        return self

    def __exit__(self, *exc):
        if not self.enabled:
            return False
        try:
            self._finish()
        except Exception as e:  # noqa: BLE001 - never fail the wrapped run
            try:
                print(f"LOAD RECORD: UNRECORDED -- recorder error "
                      f"{type(e).__name__}: {e} ({self.path})", flush=True)
            except Exception:  # noqa: BLE001
                pass
        return False

    def _finish(self) -> None:
        wall = time.perf_counter() - self._p0
        rec: dict = {
            "rule": "a timing records concurrent load",
            "label": self.label,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self._t0)),
            "wall_s": round(wall, 3),
            "cpu_count": os.cpu_count(),
            "interval_s": self.interval,
            "exclude_descendants": self.exclude_descendants,
            "process_core_limit": PROCESS_CORE_LIMIT,
            "total_core_limit": TOTAL_CORE_LIMIT,
        }
        if psutil is None:
            rec["verdict"] = "UNRECORDED"
            rec["why"] = ("note: the load record is optional and needs psutil, from the "
                          "[extra] install; nothing was recorded")
        elif self._error is not None:
            self._stop.set()
            rec["verdict"] = "UNRECORDED"
            rec["why"] = self._error
        else:
            self._stop.set()
            # __enter__ sets _error whenever it does not start the thread, and _finish runs only
            # from __exit__ when enabled, so with psutil present and no error the thread exists.
            assert self._thread is not None
            self._thread.join(timeout=5)
            try:
                self._sample()
            except Exception:  # noqa: BLE001
                pass
            # CPU deltas run from the entry snapshot to the exit one, which
            # bracket the timed window; divide by that span, not the window.
            span = time.perf_counter() - self._span0
            rec["sampled_span_s"] = round(span, 3)
            rows = []
            total = kernel = 0.0
            with self._lock:
                for key, (name, base) in self._first.items():
                    cpu = self._last[key][1] - base
                    if cpu <= 0:
                        continue
                    cores = cpu / max(span, 1e-9)
                    if name in KERNEL:
                        kernel += cpu
                        continue
                    total += cpu
                    if cores >= NOTABLE_CORE:
                        rows.append({"pid": key[0], "name": name,
                                     "cpu_s": round(cpu, 2),
                                     "avg_cores": round(cores, 3)})
                samples = list(self._samples)
            rows.sort(key=lambda r: -r["cpu_s"])
            total_cores = total / max(span, 1e-9)
            worst = rows[0] if rows else None
            rec["other_processes"] = rows
            rec["other_total_cpu_s"] = round(total, 2)
            rec["other_total_avg_cores"] = round(total_cores, 3)
            rec["kernel_avg_cores"] = round(kernel / max(span, 1e-9), 3)
            rec["samples"] = samples
            if worst and worst["avg_cores"] >= PROCESS_CORE_LIMIT:
                rec["verdict"] = "CONTAMINATED"
                rec["why"] = (f"{worst['name']} (pid {worst['pid']}) averaged "
                              f"{worst['avg_cores']:.2f} core")
            elif total_cores >= TOTAL_CORE_LIMIT:
                rec["verdict"] = "CONTAMINATED"
                rec["why"] = f"other processes together averaged {total_cores:.2f} core"
            else:
                rec["verdict"] = "CLEAN"
                rec["why"] = (f"other processes averaged {total_cores:.2f} core in "
                              f"total, none >= {PROCESS_CORE_LIMIT}")
            rec["why"] += f"; kernel {rec['kernel_avg_cores']:.2f} core, not judged"
        self.record = rec
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
        except OSError as e:
            print(f"LOAD RECORD: could not write {self.path}: {e}", flush=True)
        print(f"LOAD RECORD: {rec['verdict']} -- {rec['why']} ({self.path})", flush=True)
