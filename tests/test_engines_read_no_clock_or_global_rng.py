# SPDX-License-Identifier: BSD-3-Clause
"""The engines read no wall clock and no global random state, except where listed.

WHY THIS TEST EXISTS. A port that reproduces its original bit for bit must compute the
same bytes on every run. Two inputs can break that without any argument changing: the
wall clock (``time.time()``, ``datetime.now()``, ``time.strftime(fmt)`` with no time
argument) and process-global random state (the ``random`` module's functions, numpy's
legacy ``np.random.<fn>`` functions, an unseeded ``default_rng()`` or ``Random()``). A
clock read is legitimate when it only stamps file metadata the original also stamps
(UIOOPS's ``'Creation Time'``, SODA-2's creation date) or only times, logs or paces work;
a seeded local generator is legitimate because its stream is fixed. Anything else could
change a computed number from one run to the next.

Measured when this check was written (2026-10-01), over the four engine packages under
``src/`` (``arrayprobe``, ``arrayprobe_uiops``, ``arrayprobe_soda2``, ``uiops``): every
read found is on :data:`ALLOWLIST` with its class --

* ``a`` -- a timestamp written into file metadata that the original MATLAB/IDL writes too;
* ``b`` -- timing, logging, progress or provenance only, changing no computed value;
* ``c`` -- a seeded local generator (none needs listing today: a seeded ``Random(seed)``,
  ``default_rng(seed)`` or ``RandomState(seed)`` is not a finding; the four in use, in
  both ``min_circle`` modules, ``jit_kernels`` and ``review_agreement``/``review_sampling``,
  all pass a seed);
* ``d`` -- a clock read that reaches a computed number. One exists, kept because the
  original has the same dependence (``combine.py``'s run-year replica), and the count of
  such entries may only fall (:data:`CLASS_D_CEILING`).

No global random state is read anywhere in the four packages.

The allowlist is pinned per (file, resolved name) with an occurrence count, and is
shrink-only: a new occurrence in a listed file fails as surely as one in a new file, and
an entry whose count no longer matches fails too, so the list cannot go stale.

HOW NAMES ARE RESOLVED. Each module's imports are read into an alias table
(``import time as _time``, ``import datetime as _dt``, ``from datetime import datetime``,
``import numpy as np``), and every attribute chain or bare name is rewritten to its
dotted origin before it is compared, so ``_dt.datetime.now`` and ``datetime.now`` (after
``from datetime import datetime``) are both ``datetime.datetime.now``. The scanner is
shown to fire on a synthetic source before its silence over the real tree is trusted.
"""

from __future__ import annotations

import ast
import unittest
from collections import Counter
from pathlib import Path

from tests._repo import needs_source

_SRC = Path(__file__).resolve().parents[1] / "src"
ENGINE_PACKAGES = ("arrayprobe", "arrayprobe_uiops", "arrayprobe_soda2", "uiops")

#: Fewer modules than this means the walk found the wrong tree (144 on 2026-10-01).
MIN_MODULES_WALKED = 120

#: Fully resolved names that read the wall clock.
CLOCK_READS = frozenset(
    {f"time.{fn}" for fn in (
        "time", "time_ns", "perf_counter", "perf_counter_ns", "monotonic",
        "monotonic_ns", "process_time", "process_time_ns", "thread_time",
        "thread_time_ns")}
    | {"datetime.datetime.now", "datetime.datetime.utcnow", "datetime.datetime.today",
       "datetime.date.today"}
)

#: ``time`` functions that read the clock only when their time argument is omitted;
#: the value is the number of positional arguments below which they do.
CLOCK_WHEN_SHORT = {"time.localtime": 1, "time.gmtime": 1, "time.ctime": 1,
                    "time.asctime": 1, "time.strftime": 2}

#: Constructors of a local generator: fine with a seed, a finding without one.
LOCAL_GENERATORS = frozenset(
    {"random.Random", "numpy.random.default_rng", "numpy.random.RandomState",
     "numpy.random.Generator", "numpy.random.SeedSequence", "numpy.random.PCG64",
     "numpy.random.PCG64DXSM", "numpy.random.MT19937", "numpy.random.Philox",
     "numpy.random.SFC64", "numpy.random.BitGenerator"}
)

#: Process-global entropy that no seed controls.
GLOBAL_ENTROPY = frozenset({"os.urandom", "uuid.uuid1", "uuid.uuid4",
                            "random.SystemRandom"})

_NOW = "datetime.datetime.now"

#: (path relative to src/, resolved name) -> (occurrences, class, reason).
ALLOWLIST: dict[tuple[str, str], tuple[int, str, str]] = {
    # -- a: metadata timestamps the original writes too ---------------------------
    ("arrayprobe_uiops/matlab_compat.py", _NOW): (
        1, "a", "datestr() with no date is MATLAB's datestr(now), the 'Creation Time' form"),
    ("arrayprobe/matio.py", "time.strftime"): (
        1, "a", "MAT-file 116-byte header 'Created on:' text, as MATLAB save writes it"),
    ("arrayprobe_uiops/imgproc.py", _NOW): (
        1, "a", "imgProc_sm.m:297 'Creation Time' default when creation_time is not given"),
    ("arrayprobe/driver/run_flight.py", _NOW): (
        4, "a", "log() line prefix (b) and three 'Creation Time' values passed to the v3.5 "
                "readers (a); no computed value"),
    ("arrayprobe_soda2/export_ncdf.py", _NOW): (
        1, "a", "SODA-2 DateCreated attribute default, IDL systime() form"),
    ("arrayprobe_soda2/export_ncdf_raf.py", _NOW): (
        1, "a", "SODA-2 RAF export DateCreated attribute default, IDL systime() form"),
    ("arrayprobe_soda2/pbp_writer.py", _NOW): (
        2, "a", "SODA-2 PBP 'Date Processed' text header and DateProcessed attribute"),
    ("arrayprobe_soda2/process_2d.py", _NOW): (
        1, "a", "SODA-2 date_processed written into the SAVE file, as the IDL does"),
    ("arrayprobe_soda2/save_writer.py", "time.strftime"): (
        1, "a", "IDL SAVE TIMESTAMP record default (systime() form); tests pin it"),
    ("arrayprobe/attributed_export.py", _NOW): (
        1, "a", "export_time provenance attribute default; this package's own stamp"),
    # -- b: timing, logging, progress, provenance --------------------------------
    ("arrayprobe_uiops/spec_core.py", _NOW): (
        1, "b", "HH:MM:SS prefix of a parallel-decode progress log line"),
    ("arrayprobe/run_page.py", _NOW): (
        2, "b", "Run page: the run id's timestamp and the exit line's ISO time in the run's "
                "log; no computed value"),
    ("arrayprobe/triage_server.py", _NOW): (
        2, "b", "'at' time on a manual triage verdict record (per-particle and "
                "per-second stores); no computed value"),
    ("arrayprobe/cli.py", "time.time"): (
        3, "b", "batch progress rate and 'done in N min' message"),
    ("arrayprobe/driver/_load_record.py", "time.time"): (
        2, "b", "load-record wall-clock start and sample times (run provenance)"),
    ("arrayprobe/driver/_load_record.py", "time.perf_counter"): (
        4, "b", "load-record elapsed and per-span durations (run provenance)"),
    ("arrayprobe/driver/run_flight.py", "time.time"): (
        17, "b", "per-stage elapsed seconds in log lines and the run's total minutes"),
    ("arrayprobe/driver/run_flight.py", "time.monotonic"): (
        6, "b", "worker stall watchdog and heartbeat; decides when to kill a hung "
                "worker, never what a finished worker computes"),
    ("arrayprobe_soda2/process_2d.py", "time.monotonic"): (
        2, "b", "buffer-loop progress rate and ETA log line"),
    ("arrayprobe_soda2/process_2d_parallel.py", "time.monotonic"): (
        8, "b", "sweep, replay and total timings in log lines"),
    # -- d: the clock reaches a computed number; reproduced on purpose ------------
    ("arrayprobe_uiops/combine_fork.py", "datetime.date.today"): (
        1, "d", "_timevec_matlab_replica: combine_sizedist.m:109-110's datenum('HHMMSS') "
                "resolves to January 1 of the run year, so the time axis shifts with the "
                "calendar (the upstream finding on combine_sizedist's year); reached only "
                "when current_year is passed, the "
                "default path computes the intended axis without it"),
}

#: Entries of class ``d`` -- a clock read that reaches a computed number -- may only
#: fall in number. Each is a faithful reproduction of the original's own dependence.
CLASS_D_CEILING = 1


def _alias_table(tree: ast.Module) -> dict[str, str]:
    table: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    table[a.asname] = a.name
                else:
                    top = a.name.split(".")[0]
                    table.setdefault(top, top)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for a in node.names:
                table[a.asname or a.name] = f"{node.module}.{a.name}"
    return table


def _dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _resolve(dotted: str, table: dict[str, str]) -> str:
    head, _, rest = dotted.partition(".")
    if head not in table:
        return ""  # not an imported name: a local variable cannot be a module read
    base = table[head]
    return f"{base}.{rest}" if rest else base


def _classify(name: str, call: ast.Call | None) -> bool:
    """True when ``name`` (resolved), used as ``call`` if called, is a finding."""
    if name in CLOCK_READS or name in GLOBAL_ENTROPY:
        return True
    if name in CLOCK_WHEN_SHORT:
        return call is None or len(call.args) < CLOCK_WHEN_SHORT[name]
    if name in LOCAL_GENERATORS:
        if call is None:
            return False
        return not call.args and not any(k.arg in ("seed", "x") for k in call.keywords)
    if name.startswith("random.") and name.count(".") == 1:
        return True
    if name.startswith("numpy.random.") and name.count(".") == 2:
        return True
    return False


def scan_source(source: str) -> list[tuple[int, str]]:
    """Every (line, resolved name) in ``source`` that reads the clock or global RNG."""
    tree = ast.parse(source)
    table = _alias_table(tree)
    calls = {id(n.func): n for n in ast.walk(tree) if isinstance(n, ast.Call)}
    inner: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute):
            inner.add(id(n.value))
    hits: list[tuple[int, str]] = []
    for n in ast.walk(tree):
        if not isinstance(n, (ast.Attribute, ast.Name)):
            continue
        if isinstance(n, ast.Name) and not isinstance(n.ctx, ast.Load):
            continue
        dotted = _dotted(n)
        if dotted is None:
            continue
        name = _resolve(dotted, table)
        # Judge each chain at its longest prefix that is a known name, so
        # ``datetime.now().ctime`` and ``_dt.datetime.now`` are each counted once.
        if id(n) in inner and _classify(name, calls.get(id(n))) is False:
            continue
        if id(n) in inner:
            parent_is_finding = False
            for p in ast.walk(tree):
                if isinstance(p, ast.Attribute) and p.value is n:
                    pd = _dotted(p)
                    if pd and _classify(_resolve(pd, table), calls.get(id(p))):
                        parent_is_finding = True
                    break
            if parent_is_finding:
                continue
        if _classify(name, calls.get(id(n))):
            hits.append((n.lineno, name))
    return hits


def scan_tree() -> tuple[int, dict[tuple[str, str], list[int]]]:
    found: dict[tuple[str, str], list[int]] = {}
    walked = 0
    for pkg in ENGINE_PACKAGES:
        for path in sorted((_SRC / pkg).rglob("*.py")):
            walked += 1
            rel = path.relative_to(_SRC).as_posix()
            for line, name in scan_source(path.read_text(encoding="utf-8")):
                found.setdefault((rel, name), []).append(line)
    return walked, found


class TheScannerFires(unittest.TestCase):
    def test_it_flags_each_kind_of_read_on_a_synthetic_source(self):
        src = (
            "import time as _t\nimport datetime as _dt\nfrom datetime import datetime\n"
            "import random\nimport numpy as np\nfrom numpy.random import default_rng\n"
            "a = _t.time()\nb = _dt.datetime.now().ctime()\nc = datetime.utcnow()\n"
            "d = _t.strftime('%Y')\ne = random.random()\nnp.random.seed(0)\n"
            "f = np.random.rand(3)\ng = default_rng()\nh = random.Random()\n"
        )
        names = Counter(name for _, name in scan_source(src))
        self.assertEqual(names, Counter({
            "time.time": 1, "datetime.datetime.now": 1, "datetime.datetime.utcnow": 1,
            "time.strftime": 1, "random.random": 1, "numpy.random.seed": 1,
            "numpy.random.rand": 1, "numpy.random.default_rng": 1, "random.Random": 1,
        }))

    def test_it_stays_silent_on_seeded_generators_and_explicit_times(self):
        src = (
            "import time, random\nimport numpy as np\nimport datetime as _dt\n"
            "r = random.Random(7).shuffle\ng = np.random.default_rng(3)\n"
            "s = np.random.RandomState(seed=1)\nt = time.strftime('%Y', time.gmtime(0))\n"
            "u = _dt.time(1, 2)\nv = _dt.datetime(2016, 9, 6)\ntime.sleep(0)\n"
        )
        self.assertEqual(scan_source(src), [])


@needs_source
class TheEnginesReadNoClockOrGlobalRng(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.walked, cls.found = scan_tree()

    def test_the_walk_reached_the_engines(self):
        self.assertGreaterEqual(self.walked, MIN_MODULES_WALKED)

    def test_every_read_is_allowlisted_with_its_count(self):
        problems = []
        for key, lines in sorted(self.found.items()):
            entry = ALLOWLIST.get(key)
            if entry is None:
                problems.append(f"not allowlisted: {key[0]} {key[1]} at lines {lines}")
            elif entry[0] != len(lines):
                problems.append(f"count changed: {key[0]} {key[1]} allowlisted "
                                f"{entry[0]}, found {len(lines)} at lines {lines}")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_no_allowlist_entry_is_stale(self):
        stale = sorted(k for k in ALLOWLIST if k not in self.found)
        self.assertEqual(stale, [], f"allowlist entries that no longer occur: {stale}")

    def test_every_allowlist_entry_names_a_class_and_a_reason(self):
        for key, (count, klass, reason) in ALLOWLIST.items():
            self.assertIn(klass, ("a", "b", "c", "d"), key)
            self.assertGreater(count, 0, key)
            self.assertTrue(reason.strip(), key)

    def test_reads_that_reach_a_computed_number_only_shrink(self):
        class_d = [k for k, (_, klass, _) in ALLOWLIST.items() if klass == "d"]
        self.assertLessEqual(len(class_d), CLASS_D_CEILING, class_d)


if __name__ == "__main__":
    unittest.main()

# A repository sweep: run before every full suite by the pre-suite check
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
