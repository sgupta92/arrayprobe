# SPDX-License-Identifier: BSD-3-Clause
"""The triage server's Run page: the pure core (form -> TOML -> argv).

Design: ``RUN_PAGE_PLAN.md`` (local session notes, not shipped). The page writes the same
TOML a command-line run reads and launches the documented entry point (``arrayprobe run
<config.toml>`` for the UIOOPS engines, ``arrayprobe soda2 run <config.toml>`` for SODA-2). It
holds **no processing rule**: it validates only shape and whitelists (engine, preset, profile,
probe, paths, run name), and the driver's own ``--dry-run`` preflight is the authority on
everything else, so a refusal added to the driver reaches the page with no edit here.

Slice 2 adds the dry-run validator, the detached launch, run records and run status; the
routes and HTML are slice 3.
Every argv this module builds is a list with ``sys.executable`` as its program -- never a shell
string.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

__all__ = ["ENGINES", "PROTECTIVE_MODES", "preset_choices", "profile_choices",
           "probe_choices_v35", "probe_choices_soda2", "build_toml", "build_argv",
           "validate_form", "raw_list", "dry_run", "launch_detached", "new_run_id",
           "start_run", "write_record", "read_record", "list_runs", "run_status"]

#: The three engines a run may name (``config._ENGINES``); 3.5 is the default.
ENGINES = ("3.5", "soda2", "3.1.4")
PROTECTIVE_MODES = ("auto", "on", "off")
#: ``[soda2]`` fields the form may set beyond the probe row, ``fn`` and ``outdir``; anything
#: else stays in the written file for the user to edit (plan section 0, SODA-2 GUI subset).
SODA2_FORM_FIELDS = ("date", "starttime", "stoptime", "timeoffset")
_STAGES_OK = re.compile(r"^[234]+$")
_NAME_OK = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
#: The driver's own sentence (``run_flight.main``), so the page and the driver say the same thing.
REFUSAL_314 = ("--engine 3.1.4 needs --port-validation: v3.1.4 is the ORACLES-validation "
               "anchor only, and its output is stamped port validation, not for quoting")


def preset_choices() -> tuple[str, ...]:
    """``run_flight.PRESETS`` keys, through the CLI's one loader of the driver."""
    from .cli import _load_run_flight
    return tuple(_load_run_flight().PRESETS)


def profile_choices() -> tuple[str, ...]:
    """Every profile name a config file may select (``config.PROFILES``)."""
    from .config import PROFILES
    return tuple(sorted(PROFILES))


def probe_choices_v35() -> tuple[str, ...]:
    """``arrayprobe_uiops.imgproc.PROBES_V35`` keys -- the UIOOPS ``[run].probe`` names."""
    from arrayprobe_uiops.imgproc import PROBES_V35
    return tuple(PROBES_V35)


def probe_choices_soda2() -> tuple[str, ...]:
    """SODA-2's probe table: ``arrayprobe_soda2.probespecs.PROBE_NAMES``
    (``soda2_probespecs.pro``'s ``probename`` column)."""
    from arrayprobe_soda2.probespecs import PROBE_NAMES
    return tuple(PROBE_NAMES)


def raw_list(value: Any) -> list[str]:
    """The form's raw field -- a list, or one path per line -- as a list of non-blank strings."""
    items: Iterable[Any] = value.splitlines() if isinstance(value, str) else (value or [])
    return [str(s).strip() for s in items if str(s).strip()]


def _toml_value(value: Any) -> str:
    """A TOML literal for a str/int/float/bool or a list of them. ``json.dumps`` quoting is
    valid TOML for basic strings (backslashes and ``\\uXXXX`` escapes included)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, (int, float, str)):
        return json.dumps(value)
    raise TypeError(f"no TOML literal for {type(value).__name__}: {value!r}")


def _plain(value: Any) -> Any:
    """A probe-table value as a Python scalar/list. float32 goes through its shortest repr so
    ``5.1e-08`` is written as typed in ``soda2_probespecs.pro``, not as a widened double."""
    import numpy as np
    if isinstance(value, np.ndarray):
        return [_plain(v) for v in value.tolist()]
    if isinstance(value, np.floating):
        return float(str(value))
    if isinstance(value, np.integer):
        return int(value)
    return value


def _table(name: str, rows: Mapping[str, Any]) -> list[str]:
    return [f"[{name}]", *(f"{k} = {_toml_value(v)}" for k, v in rows.items()), ""]


def build_toml(form: Mapping[str, Any]) -> str:
    """The configuration file a validated form describes. Pure; raw and out are written
    resolved and absolute, so the file reads the same wherever it is saved."""
    engine = str(form["engine"])
    raws = [str(Path(p).resolve()) for p in raw_list(form.get("raw"))]
    out = str(Path(str(form["out"])).resolve())
    lines = ["# Written by the triage server's Run page; edit and re-run with the same command.",
             ""]
    if engine == "soda2":
        from arrayprobe_soda2.probespecs import soda2_probespecs
        row = soda2_probespecs(name=str(form["probe"]))
        assert isinstance(row, dict), "a scalar name returns one row"
        lines += _table("run", {"engine": "soda2", "jit": bool(form.get("jit", False))})
        soda2: dict[str, Any] = {k: _plain(v) for k, v in row.items()}
        soda2["fn"] = raws[0] if len(raws) == 1 else raws
        soda2["outdir"] = out + os.sep
        for key in SODA2_FORM_FIELDS:
            if form.get(key) not in (None, ""):
                soda2[key] = form[key]
        lines += _table("soda2", soda2)
        return "\n".join(lines)
    lines += _table("fidelity", {"profile": str(form["profile"])})
    run: dict[str, Any] = {"engine": engine, "preset": str(form["preset"]), "raw": raws,
                           "out": out, "stages": str(form.get("stages") or "234")}
    if form.get("probe"):
        run["probe"] = str(form["probe"])
    if form.get("tas_file"):
        run["tas_file"] = str(Path(str(form["tas_file"])).resolve())
    lines += _table("run", run)
    return "\n".join(lines)


def _int(form: Mapping[str, Any], key: str, default: int = 1) -> int:
    return int(form.get(key) or default)


def build_argv(form: Mapping[str, Any], toml_path: Path | str, *, dry_run: bool) -> list[str]:
    """The documented entry point's argv for a validated form. Always a list, program
    ``sys.executable``; run-shape flags (``--jobs`` and friends) ride on the argv, not the file,
    exactly as ``arrayprobe run`` treats them.

    SODA-2 has no ``--dry-run``; its preflight is ``arrayprobe soda2 enhancements <config>``,
    which loads and checks the file (and its enhancement table) and runs nothing.
    """
    base = [sys.executable, "-m", "arrayprobe"]
    toml_s = str(toml_path)
    engine = str(form["engine"])
    if engine == "soda2":
        protective = str(form.get("protective") or "auto")
        if dry_run:
            return [*base, "soda2", "enhancements", toml_s, "--protective", protective]
        argv = [*base, "soda2", "run", toml_s, "--out", str(Path(str(form["out"])).resolve()),
                "--jobs", str(_int(form, "jobs"))]
        if _int(form, "chunks", 0) > 1:
            argv += ["--chunks", str(_int(form, "chunks"))]
        if form.get("jit"):
            argv.append("--jit")
        return argv + ["--protective", protective]
    # --yes is mandatory: a detached run has no terminal to answer the confirmation gate.
    argv = [*base, "run", toml_s, "--yes"]
    for key in ("jobs", "s2_jobs", "chunks"):
        argv += [f"--{key.replace('_', '-')}", str(_int(form, key))]
    if form.get("jit"):
        argv.append("--jit")
    if form.get("port_validation"):
        # Forwarded as ticked, never added from the engine: the driver's refusal is the last word.
        argv.append("--port-validation")
    if dry_run:
        argv.append("--dry-run")
    return argv


def validate_form(form: Mapping[str, Any], *, presets: Iterable[str] | None = None,
                  profiles: Iterable[str] | None = None,
                  probes_v35: Iterable[str] | None = None,
                  soda2_probes: Iterable[str] | None = None) -> list[str]:
    """Every whitelist and shape problem with ``form``, empty when the form may be written.
    The tables default to the discovered ones; tests inject their own."""
    errors: list[str] = []
    engine = form.get("engine")
    if engine not in ENGINES:
        return [f"engine must be one of {list(ENGINES)}; got {engine!r}"]
    name = form.get("name", "")
    if not isinstance(name, str) or not _NAME_OK.match(name):
        errors.append(f"run name must be 1-64 of letters, digits, '.', '_', '-'; got {name!r}")
    raws = raw_list(form.get("raw"))
    if not raws:
        errors.append("give at least one raw file, one path per line")
    for p in raws:
        if not Path(p).is_file():
            errors.append(f"raw file not found: {p}")
    out = form.get("out")
    if not isinstance(out, str) or not out.strip():
        errors.append("give an output folder")
    else:
        po = Path(out).resolve()
        if po.exists() and not po.is_dir():
            errors.append(f"output folder is a file: {out}")
        elif not po.exists() and not po.parent.is_dir():
            errors.append(f"output folder's parent does not exist: {po.parent}")
    for key in ("jobs", "s2_jobs", "chunks"):
        value = form.get(key, 1)
        if isinstance(value, bool) or not isinstance(value, (int, str)) \
                or not str(value).isdigit() or int(value) < 1:
            errors.append(f"{key} must be a whole number >= 1; got {value!r}")
    protective = form.get("protective") or "auto"
    if protective not in PROTECTIVE_MODES:
        errors.append(f"protective must be one of {list(PROTECTIVE_MODES)}; got {protective!r}")
    if engine == "soda2":
        table = soda2_probes if soda2_probes is not None else probe_choices_soda2()
        if form.get("probe") not in set(table):
            errors.append(f"SODA-2 probe {form.get('probe')!r} is not in soda2_probespecs")
        if form.get("port_validation"):
            errors.append("--port-validation applies to engine 3.1.4 only")
        return errors
    # UIOOPS engines.
    if protective != "auto":
        # `arrayprobe run` takes no --protective; the driver applies its own default ("auto").
        errors.append("protective is set by the driver for UIOPS runs; `arrayprobe run` has no "
                      "--protective, so only 'auto' can be honoured")
    if engine == "3.1.4" and not form.get("port_validation"):
        errors.append(REFUSAL_314)
    if engine != "3.1.4" and form.get("port_validation"):
        errors.append("--port-validation applies to engine 3.1.4 only")
    if form.get("preset") not in set(presets if presets is not None else preset_choices()):
        errors.append(f"unknown preset {form.get('preset')!r}")
    if form.get("profile") not in set(profiles if profiles is not None else profile_choices()):
        errors.append(f"unknown profile {form.get('profile')!r}")
    probe = form.get("probe")
    if probe not in (None, "") and probe not in set(
            probes_v35 if probes_v35 is not None else probe_choices_v35()):
        errors.append(f"unknown probe {probe!r}")
    stages = str(form.get("stages") or "234")
    if not _STAGES_OK.match(stages):
        errors.append(f"stages must use only 2, 3 and 4; got {stages!r}")
    tas = form.get("tas_file")
    if tas not in (None, "") and not Path(str(tas)).is_file():
        errors.append(f"tas file not found: {tas}")
    return errors


# ---------------------------------------------------------------------------------------------
# Slice 2: dry run, detached launch, run records, run status.
# ---------------------------------------------------------------------------------------------

#: The directory under the chosen output folder that holds one folder per launched run.
RUNS_DIR = "_runs"
_RUN_ID_OK = re.compile(r"^\d{8}-\d{6}-[A-Za-z0-9_.-]{1,64}$")
#: The wrapper's last line. The header
#: written at launch never contains the marker word, so a grep cannot match a run that has not
#: ended (``tests/test_launch_detached.py::TheCompletionMarkerIsNotCounterfeited``).
_EXIT_LINE = re.compile(r"^=== (?P<run_id>\S+) exited (?P<code>-?\d+) ")
_VERDICT_LINE = re.compile(r"^(OK\b|FAILED\b|Traceback\b|.*\brefus(ed|es)\b)", re.IGNORECASE)
#: Windows process-creation flags for a run that must outlive the server (``subprocess``'s
#: constants, spelled out so the module imports on POSIX).
CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008


def dry_run(argv: list[str], cwd: Path | str, *, timeout: float = 120,
            launcher: Any = None) -> tuple[int, str]:
    """Run the driver's preflight (``argv`` from ``build_argv(..., dry_run=True)``) in the
    foreground and return ``(returncode, combined output)`` verbatim. A timeout is reported as
    returncode -1 with what was captured. ``launcher`` defaults to ``subprocess.run``."""
    import subprocess
    run = launcher if launcher is not None else subprocess.run
    if not isinstance(argv, list):
        raise TypeError("argv must be a list; no shell string is ever run")
    try:
        done = run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                   stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout if isinstance(exc.stdout, str) else ""
        return -1, partial + f"\n[dry run did not finish within {timeout:g} s]"
    return int(done.returncode), (done.stdout or "") + (done.stderr or "")


def _wrapped(run_id: str, argv: list[str]) -> list[str]:
    """``argv`` behind this module's wrapper, which writes the exit line when the run ends."""
    return [sys.executable, "-m", "arrayprobe.run_page", "_wrap", run_id, "--", *argv]


def launch_detached(argv: list[str], log_path: Path | str, cwd: Path | str, *,
                    run_id: str, popen: Any = None) -> int:
    """Start ``argv`` so it outlives the server: its own
    session (Windows: a new process group, detached from the console), stdin from the null
    device, stdout and stderr straight to ``log_path`` (never a pipe: it can hang), and
    a wrapper that writes ``=== <run_id> exited <code> <date> ===`` as the log's last line.
    Returns the wrapper's PID; the wrapper lives exactly as long as the run.
    ``popen`` defaults to ``subprocess.Popen``."""
    import subprocess
    if not isinstance(argv, list):
        raise TypeError("argv must be a list; no shell string is ever run")
    if not _RUN_ID_OK.match(run_id):
        raise ValueError(f"run id {run_id!r} is not one new_run_id makes")
    start = popen if popen is not None else subprocess.Popen
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {"cwd": str(cwd), "stdin": subprocess.DEVNULL,
                              "stderr": subprocess.STDOUT, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    with open(log_path, "ab") as log:
        log.write((f"=== {run_id} launched detached {_now_iso()} ===\n"
                   f"=== command: {' '.join(argv)} ===\n").encode())
        log.flush()
        proc = start(_wrapped(run_id, argv), stdout=log, **kwargs)
    pid = int(proc.pid)
    with open(log_path, "ab") as log:
        log.write((f"=== pid: {pid} (the wrapper; its python child does the work) ===\n"
                   "=== a log that stopped growing is not a dead run: the run has ended only "
                   "once a final line here reports its exit code ===\n").encode())
    return pid


def _hold_wakelock() -> None:
    """Keep Windows from sleeping while this process lives (``_detached_wrapper.sh``'s
    ES_CONTINUOUS|ES_SYSTEM_REQUIRED); released when the process exits. No-op elsewhere."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 -- a wakelock must never be the reason a run fails
        pass


def _wrap(args: list[str]) -> int:
    """``python -m arrayprobe.run_page _wrap <run_id> -- <argv...>``: run argv with this
    process's stdout and stderr (the log), then print the exit line."""
    import subprocess
    if len(args) < 3 or args[1] != "--" or not _RUN_ID_OK.match(args[0]):
        print("usage: python -m arrayprobe.run_page _wrap <run_id> -- <command> [args...]",
              file=sys.stderr)
        return 2
    run_id, argv = args[0], args[2:]
    _hold_wakelock()
    sys.stdout.flush()
    try:
        code = subprocess.call(argv, stdin=subprocess.DEVNULL)
    except OSError as exc:
        print(f"could not start {argv[0]!r}: {exc}", flush=True)
        code = 127
    print(f"=== {run_id} exited {code} {_now_iso()} ===", flush=True)
    return code


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def new_run_id(name: str, now: Any = None) -> str:
    """``<YYYYMMDD-HHMMSS>-<name>``; ``name`` must satisfy the form's whitelist."""
    import datetime as _dt
    if not isinstance(name, str) or not _NAME_OK.match(name):
        raise ValueError(f"run name {name!r} is not whitelisted")
    stamp = (now or _dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{name}"


def _runs_root(out: Path | str) -> Path:
    return Path(out).resolve() / RUNS_DIR


def write_record(out: Path | str, record: Mapping[str, Any]) -> Path:
    """Write ``record`` as ``<out>/_runs/<run_id>/run.json``; returns the path."""
    run_id = str(record["run_id"])
    if not _RUN_ID_OK.match(run_id):
        raise ValueError(f"run id {run_id!r} is not one new_run_id makes")
    path = _runs_root(out) / run_id / "run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(record), indent=2), encoding="utf-8")
    return path


def list_runs(out: Path | str) -> list[str]:
    """Run ids recorded under ``out``, newest first: folders whose name has the run-id shape
    and which hold a ``run.json``."""
    root = _runs_root(out)
    if not root.is_dir():
        return []
    ids = [p.name for p in root.iterdir()
           if p.is_dir() and _RUN_ID_OK.match(p.name) and (p / "run.json").is_file()]
    return sorted(ids, reverse=True)


def read_record(out: Path | str, run_id: str) -> dict[str, Any] | None:
    """The record for ``run_id``, or None. ``run_id`` reaches a path only after it matched an
    entry ``list_runs`` found on disk (the ``_valid_flight`` doctrine)."""
    if run_id not in list_runs(out):
        return None
    loaded: dict[str, Any] = json.loads(
        (_runs_root(out) / run_id / "run.json").read_text(encoding="utf-8"))
    return loaded


def start_run(form: Mapping[str, Any], *, cwd: Path | str | None = None, popen: Any = None,
              now: Any = None) -> dict[str, Any]:
    """Write the form's TOML into a new run folder, launch it detached and record it. The form
    must already have passed ``validate_form``; the run name is checked again here because it
    becomes a path."""
    run_id = new_run_id(str(form.get("name", "")), now)
    out = Path(str(form["out"])).resolve()
    run_dir = _runs_root(out) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    toml_path = run_dir / "config.toml"
    toml_path.write_text(build_toml(form), encoding="utf-8")
    log_path = run_dir / "run.log"
    argv = build_argv(form, toml_path, dry_run=False)
    started = _now_iso()
    pid = launch_detached(argv, log_path, cwd if cwd is not None else out, run_id=run_id,
                          popen=popen)
    record = {"run_id": run_id, "pid": pid, "argv": argv, "toml": str(toml_path),
              "log": str(log_path), "out": str(out), "engine": str(form["engine"]),
              "started": started}
    write_record(out, record)
    return record


def _pid_alive(pid: int) -> bool:
    """Whether ``pid`` is running. Windows asks the kernel (MSYS ``ps`` misses native
    grandchildren, 2026-09-13); POSIX uses signal 0."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _started_epoch(record: Mapping[str, Any]) -> float:
    import datetime as _dt
    try:
        return _dt.datetime.fromisoformat(str(record["started"])).timestamp()
    except (KeyError, ValueError):
        return 0.0


def run_status(record: Mapping[str, Any], *, tail_lines: int = 40,
               alive: Any = None) -> dict[str, Any]:
    """What the page shows for one run: state, exit code (from the wrapper's exit line), the
    log's tail, verdict lines (OK / FAILED / Traceback / refused), the ``.call`` stamps written
    under ``out`` since the start, and the newest output file's mtime -- a chunked or ``--jobs``
    run is silent in its log for long stretches, so that mtime is the heartbeat.
    ``alive`` defaults to a process-table check of ``record['pid']``."""
    check = alive if alive is not None else _pid_alive
    log = Path(str(record["log"]))
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    lines = text.splitlines()
    exit_code: int | None = None
    for line in reversed(lines):
        m = _EXIT_LINE.match(line)
        if m and m.group("run_id") == record.get("run_id"):
            exit_code = int(m.group("code"))
            break
    out = Path(str(record["out"]))
    since = _started_epoch(record)
    calls: list[str] = []
    newest = 0.0
    if out.is_dir():
        for p in out.rglob("*"):
            rel = p.relative_to(out)
            if rel.parts[:1] == (RUNS_DIR,) or not p.is_file():
                continue
            mtime = p.stat().st_mtime
            newest = max(newest, mtime)
            if p.suffix == ".call" and mtime >= since - 1:
                calls.append(rel.as_posix())
    is_alive = exit_code is None and bool(check(int(record.get("pid", 0))))
    if exit_code is not None:
        state = "finished" if exit_code == 0 else "failed"
    else:
        state = "running" if is_alive else "ended without an exit line"
    return {"run_id": record.get("run_id"), "state": state, "alive": is_alive,
            "exit_code": exit_code, "log_tail": lines[-tail_lines:],
            "verdict_lines": [ln for ln in lines if _VERDICT_LINE.match(ln)],
            "call_files": sorted(calls), "newest_output_mtime": newest or None}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "_wrap":
        sys.exit(_wrap(sys.argv[2:]))
    print("usage: python -m arrayprobe.run_page _wrap <run_id> -- <command> [args...]",
          file=sys.stderr)
    sys.exit(2)


# --- HTTP surface (slice 3): the triage server's /run and /runs routes call these --------------

def _esc(value: Any) -> str:
    import html
    return html.escape(str(value))


def _options(values: Iterable[str]) -> str:
    return "".join(f'<option value="{_esc(v)}">{_esc(v)}</option>' for v in values)


def render_form() -> str:
    """The Run page: the form, posted as JSON to ``/run`` (``dry_run`` true first)."""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Run a flight</title></head>
<body><h1>Run a flight</h1><p><a href="/">index</a> · <a href="/runs">runs</a></p>
<form id="f">
<label>Engine <select name="engine">{_options(ENGINES)}</select></label><br>
<label>Preset <select name="preset">{_options(preset_choices())}</select></label><br>
<label>Profile <select name="profile">
<option value=""></option>{_options(profile_choices())}</select></label><br>
<label>Probe (v3.5) <select name="probe">
<option value=""></option>{_options(probe_choices_v35())}</select></label><br>
<label>Probe (SODA-2) <select name="soda2_probe">
<option value=""></option>{_options(probe_choices_soda2())}</select></label><br>
<label>Raw file(s) <input name="raw" size="80"></label><br>
<label>Output folder <input name="out" size="80"></label><br>
<label>Run name <input name="name"></label><br>
<label>Protective <select name="protective">{_options(PROTECTIVE_MODES)}</select></label><br>
<button type="button" data-dry="1">Check (dry run)</button>
<button type="button" data-dry="0">Launch</button>
</form><pre id="out"></pre>
<script>
document.querySelectorAll('#f button').forEach(function (b) {{
  b.onclick = function () {{
    var form = {{}};
    new FormData(document.getElementById('f')).forEach(function (v, k) {{
      if (v !== '') form[k] = v;
    }});
    form.dry_run = b.dataset.dry === '1';
    fetch('/run', {{method: 'POST', headers: {{'Content-Type': 'application/json'}},
                   body: JSON.stringify(form)}})
      .then(function (r) {{ return r.json(); }})
      .then(function (j) {{
        if (j.run_id && !form.dry_run) {{ location.href = '/runs/' + j.run_id; return; }}
        document.getElementById('out').textContent =
          (j.errors || []).join('\n') + (j.dry_run_text || '');
      }});
  }};
}});
</script></body></html>"""


def render_runs(run_root: Path | str | None) -> str:
    """HTML for ``GET /runs``: the run ids recorded under ``run_root``, newest first, each
    linked to its page; ``None`` (no root yet) lists none."""
    ids = list_runs(run_root) if run_root is not None else []
    rows = "".join(f'<li><a href="/runs/{_esc(i)}">{_esc(i)}</a></li>' for i in ids)
    return (f"<!doctype html><html><head><meta charset=\"utf-8\"><title>Runs</title></head><body>"
            f"<h1>Runs</h1><p><a href=\"/run\">Run a flight</a></p><ul>{rows or '<li>none</li>'}"
            f"</ul></body></html>")


def render_run(record: Mapping[str, Any], status: Mapping[str, Any]) -> str:
    """HTML for ``GET /runs/<run_id>``: state, exit code, ``.call`` stamps and the
    HTML-escaped log tail from ``run_status``; the page refreshes every 10 s."""
    tail = "\n".join(_esc(line) for line in status.get("log_tail", []))
    calls = "".join(f"<li>{_esc(c)}</li>" for c in status.get("call_files", []))
    return (f"<!doctype html><html><head><meta charset=\"utf-8\"><title>Run "
            f"{_esc(record.get('run_id'))}</title><meta http-equiv=\"refresh\" content=\"10\">"
            f"</head><body><h1>Run {_esc(record.get('run_id'))}</h1>"
            f"<p><a href=\"/runs\">runs</a></p><p>state: {_esc(status.get('state'))}, exit: "
            f"{_esc(status.get('exit_code'))}</p><h2>Stamps</h2><ul>{calls}</ul>"
            f"<h2>Log tail</h2><pre>{tail}</pre></body></html>")


def same_origin(headers: Any, port: int) -> bool:
    """True when ``Host`` (and ``Origin``, when sent) name this server on the loopback
    address. Guards the one route that starts a process against a page from another origin."""
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    if headers.get("Host", "") not in allowed_hosts:
        return False
    origin = headers.get("Origin")
    return origin is None or origin in {f"http://{h}" for h in allowed_hosts}


def handle_post(form: Mapping[str, Any], headers: Any, port: int, *,
                cwd: Path | str | None = None) -> tuple[int, dict[str, Any]]:
    """``(status, JSON body)`` for ``POST /run``: refuse a foreign origin, validate against the
    whitelists, then either dry-run the driver's preflight or launch detached."""
    if not same_origin(headers, port):
        return 403, {"ok": False, "errors": ["cross-origin request refused"]}
    errors = validate_form(form)
    if errors:
        return 400, {"ok": False, "errors": errors}
    if form.get("dry_run"):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="arrayprobe_run_") as tmp:
            toml_path = Path(tmp) / "config.toml"
            toml_path.write_text(build_toml(form), encoding="utf-8")
            code, text = dry_run(build_argv(form, toml_path, dry_run=True),
                                 cwd if cwd is not None else tmp)
        return 200, {"ok": code == 0, "errors": [], "dry_run_text": text, "run_id": None}
    record = start_run(form, cwd=cwd)
    return 200, {"ok": True, "errors": [], "dry_run_text": "", "run_id": record["run_id"]}


def get_run_page(run_root: Path | str | None, run_id: str) -> tuple[int, str]:
    """``(status, HTML)`` for ``GET /runs/<run_id>``. The id reaches a path only after it
    matched a record listed on disk."""
    if run_root is None or run_id not in list_runs(run_root):
        return 404, f"unknown run {_esc(run_id)!r}"
    record = read_record(run_root, run_id)
    if record is None:
        return 404, f"unknown run {_esc(run_id)!r}"
    return 200, render_run(record, run_status(record))
