# SPDX-License-Identifier: BSD-3-Clause
"""Open every input a long run needs, before the long run starts.

**The failure this replaces, measured 2026-09-20.** A run died with
``KeyError: 'TAS'`` **754 seconds in** — after the whole S2 decode had
finished — because the aircraft file it was handed does not use UIOOPS's
variable names and nothing had opened it. The information needed to refuse was
available in the first second of the run: the file was on disk, and the names
it carries are in its header. Thirteen minutes of decode were spent to learn
something a single ``Dataset(...).variables`` call answers.

That is the whole idea. This tool **opens** each input the way the stage that
consumes it will open it, and reports what it could not read. It computes
nothing, writes nothing, and takes no position on whether the run is a good
idea — it answers one question: *will every input this run needs be readable
when the run reaches it?*

**Where it lives.** It could have been written
inside ``scripts/run_flight.py``; it lives here
instead, as a module with its own entry point, for two reasons. The driver was
held by another lane when this was built, and — the durable reason — a
preflight that only exists inside the driver cannot be run *before* deciding
to launch the driver, which is exactly when its answer is worth the most. The
wiring into ``run_flight.py`` is then one call to :func:`check_inputs`, and the
tool stays usable on its own:

    .venv/Scripts/python.exe scripts/preflight_inputs.py RAW.2DS \\
        --tas-file flightData.cdf --iat-file 2DS_intArrThreshold.cdf --out _decoded

Exit ``0`` when every input opened, ``2`` when any did not. Nothing about this
changes a computed number, so it is tooling in the port's sense
(the test being whether it moves a written byte).

**What this is not.** It is not a validity check on the *contents* — a TAS
array of the wrong length, or thresholds for the wrong flight, pass here. The
claim is narrow and stated that way deliberately: each named input exists and
yields the variable its consumer asks for by name. A check that promised more
than it tests would be the third silent guard this project has had.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from arrayprobe.tools import tas_sources as _tas_sources

#: The (true-airspeed, time) variable-name pairs an aircraft file may use, in
#: the order ``run_flight._aircraft_series`` tries them. **This table is a
#: second copy on purpose, and it is checked against the first**:
#: ``tests/test_preflight_opens_inputs.py`` reads ``_TAS_VARIANTS`` out of
#: ``scripts/run_flight.py``'s own source and fails if the two disagree. A
#: preflight that accepted a name the run then rejects — or rejected one the
#: run accepts — would be worse than no preflight, because it would be trusted.
#: Neither side may grow a name that was not read off a real file first.
#:
#: Since 2026-09-23 both copies derive from one registry,
#: :data:`arrayprobe.tools.tas_sources.SOURCES`, each entry read off a real file.
#: This copy had stayed a two-row literal after the driver moved to the registry, so it
#: refused the ORACLES merge file (``True_Air_Speed``/``Start_UTC``) the run accepts.
TAS_VARIANTS: tuple[tuple[str, str], ...] = tuple(
    (_src.tas_var, _src.time_var) for _src in _tas_sources.SOURCES)

#: ``sizedist.py:1409-1411`` opens the interarrival-threshold file and reads
#: exactly this variable. A file that exists and does not carry it fails the
#: run at the shattering block, deep inside S4.
IAT_VARIABLE = "threshold"


@dataclass(frozen=True)
class Problem:
    """One input that will not be readable when the run reaches it."""

    kind: str
    path: str
    why: str

    def __str__(self) -> str:  # pragma: no cover - exercised through report()
        return f"{self.kind} {self.path}: {self.why}"


def _variables(path: str | os.PathLike[str]) -> list[str]:
    """The variable names a netCDF file carries, or raise.

    Imported lazily so that ``--help`` and the argument surface work in an
    environment without netCDF4 — the preflight refusing to start is itself a
    preflight failure, and a confusing one.
    """
    from netCDF4 import Dataset  # noqa: PLC0415 - deliberate, see docstring

    with Dataset(str(path), "r") as ds:
        return list(ds.variables)


def _check_readable_file(kind: str, path: Path) -> Problem | None:
    if not path.exists():
        return Problem(kind, str(path), "does not exist")
    if not path.is_file():
        return Problem(kind, str(path), "is not a file")
    try:
        with path.open("rb") as fh:
            fh.read(1)
    except OSError as exc:
        return Problem(kind, str(path), f"cannot be opened for reading: {exc}")
    if path.stat().st_size == 0:
        return Problem(kind, str(path), "is empty (0 bytes)")
    return None


def check_tas_file(path: str | os.PathLike[str],
                   variants: tuple[tuple[str, str], ...] = TAS_VARIANTS,
                   ) -> list[Problem]:
    """The aircraft file, opened the way ``_aircraft_series`` opens it.

    This is the check that would have refused the 2026-09-20 run in its first
    second instead of its 755th.
    """
    p = Path(path)
    bad = _check_readable_file("--tas-file", p)
    if bad is not None:
        return [bad]
    try:
        present = _variables(p)
    except Exception as exc:  # netCDF4 raises OSError, but not only
        return [Problem("--tas-file", str(p),
                        f"exists but cannot be read as a netCDF file: {exc}")]
    for tas_name, time_name in variants:
        if tas_name in present and time_name in present:
            return []
    tried = ", ".join(f"{t}/{ti}" for t, ti in variants)
    return [Problem(
        "--tas-file", str(p),
        f"carries no true-airspeed/time pair. Tried {tried}. It carries: "
        f"{sorted(present)}. Add the pair to _TAS_VARIANTS in run_flight.py "
        f"once you have read it out of the file -- do not guess a name")]


def check_iat_file(path: str | os.PathLike[str]) -> list[Problem]:
    """The interarrival-threshold file, if one is named.

    **A named-but-absent file is not an error**, and that is not an oversight:
    ``sizeDist.m:65`` sets ``iaThreshFile = 'NONE'`` and falls back to the
    per-probe default, and the archived product was made exactly
    that way (the ``_MISSING`` convention). So absence returns
    no problem. A file that *is* there and cannot be opened, or does not carry
    ``threshold``, fails S4 deep in the shattering block and is a problem.
    """
    p = Path(path)
    if not p.exists():
        return []
    bad = _check_readable_file("--iat-file", p)
    if bad is not None:
        return [bad]
    try:
        present = _variables(p)
    except Exception as exc:
        return [Problem("--iat-file", str(p),
                        f"exists but cannot be read as a netCDF file: {exc}")]
    if IAT_VARIABLE not in present:
        return [Problem(
            "--iat-file", str(p),
            f"carries no {IAT_VARIABLE!r} variable (sizedist.py:1409-1411 reads "
            f"it by that name). It carries: {sorted(present)}")]
    return []


def check_out_dir(path: str | os.PathLike[str]) -> list[Problem]:
    """The output directory exists, or can be made, and accepts a write."""
    p = Path(path)
    if p.exists() and not p.is_dir():
        return [Problem("--out", str(p), "exists and is not a directory")]
    probe = p / ".preflight_write_probe"
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe.write_text("", encoding="utf-8")
    except OSError as exc:
        return [Problem("--out", str(p), f"is not writable: {exc}")]
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
    return []


def check_inputs(raws=(), tas_file=None, iat_file=None, out_dir=None,
                 tas_variants: tuple[tuple[str, str], ...] = TAS_VARIANTS,
                 ) -> list[Problem]:
    """Every named input, opened. Returns the problems, empty when all opened.

    Deliberately returns *all* problems rather than raising on the first: a
    long run is launched once, and being told about one unreadable input per
    attempt is how a preflight becomes something people skip.
    """
    problems: list[Problem] = []
    for raw in raws:
        bad = _check_readable_file("raw", Path(raw))
        if bad is not None:
            problems.append(bad)
    if tas_file:
        problems += check_tas_file(tas_file, tas_variants)
    if iat_file:
        problems += check_iat_file(iat_file)
    if out_dir is not None:
        problems += check_out_dir(out_dir)
    return problems


def report(problems: list[Problem], n_checked: int) -> str:
    """The preflight verdict as printed lines: one ok line, or each refused input and how
    to proceed."""
    if not problems:
        return f"preflight  {n_checked} input(s) opened; nothing refused"
    lines = [f"preflight  REFUSED: {len(problems)} of {n_checked} input(s) "
             f"could not be read"]
    lines += [f"preflight    {p}" for p in problems]
    lines.append("preflight  nothing was run. Fix the above, or drop the flag "
                 "that names the input, and launch again.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Command line: open every named input, print the report, and return 2 if any was
    refused, else 0."""
    ap = argparse.ArgumentParser(
        prog="preflight_inputs.py",
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raws", nargs="*", help="raw probe files the run will decode")
    ap.add_argument("--tas-file", default=None,
                    help="the aircraft file run_flight.py would be given")
    ap.add_argument("--iat-file", default=None,
                    help="sizeDist's optional twelfth argument; a named-but-absent "
                         "file is valid (the _MISSING convention) and passes")
    ap.add_argument("--out", default=None,
                    help="the output directory the run will write into")
    args = ap.parse_args(argv)

    n = len(args.raws) + sum(
        1 for x in (args.tas_file, args.iat_file, args.out) if x)
    problems = check_inputs(raws=args.raws, tas_file=args.tas_file,
                            iat_file=args.iat_file, out_dir=args.out)
    print(report(problems, n))
    return 2 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
