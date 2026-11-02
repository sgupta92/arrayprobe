# SPDX-License-Identifier: BSD-3-Clause
"""Stratified review samples that state their own coverage.

**What the plan asked for:** *"stratified sampling as an object:
``Sample(flight, by=[reject_code, size_bin, habit], n_per_stratum)`` writing a
queue file, so a labelled set can state its own coverage."*

**Why the last clause is the whole point.** A labelled set built by opening the
flight page and clicking through whatever looks interesting cannot say what it
covers, so an accuracy number computed from it cannot say what it is an accuracy
*over*. What this writes carries its strata, its per-stratum counts and the seed
that produced it in the same file as the particle list, so the coverage
statement is part of the artefact rather than something reconstructed afterwards
from memory.

**Under-filled strata are reported, never quietly dropped.** A stratum with
fewer particles than asked for takes what it has and says so; a stratum the
flight has none of is listed with a count of zero rather than omitted. Both are
findings about the flight -- "this flight has no particle over 1 mm" is exactly
what a reviewer needs before reading an accuracy number, and it is invisible if
empty strata simply do not appear in the file.

**This changes no computed number.** It selects which particles a person is
shown, in what order. That is why it sits in the port beside ``triage_server``
rather than in ``enhancements`` (visualisation and manual
labelling never change a computed number).

The file it writes is the shape ``triage_server._load_queue_file`` already
reads::

    {"<queue name>": [{"flight": ..., "particle_index": ..., "note": ...}, ...]}

with the coverage under a reserved, underscore-prefixed key.

``_load_queue_file`` skips underscore-prefixed keys by rule, so the coverage
block is not read as a queue -- found by the test that asserted the
server could read what this writes, which is why that test exists rather than a
comment saying the shapes match.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = [
    "COVERAGE_KEY",
    "SIZE_EDGES",
    "STRATIFIERS",
    "Sample",
    "Stratum",
    "full_axis",
    "stratum_labels",
]

#: Where the coverage statement lives in the queue file. Underscore-prefixed so
#: it can never collide with a queue name, and so a reader can skip it by a rule
#: rather than by knowing this particular string.
COVERAGE_KEY = "_coverage"

#: The strata this understands, and the ``proc`` variable each is read from.
#: A caller naming anything else is refused rather than quietly given one
#: stratum -- that failure would produce a "stratified" sample that is not one,
#: and nothing downstream could tell.
STRATIFIERS = {
    "reject_code": "image_auto_reject",
    "habit": "holroyd_habit",
    "size_bin": "image_diam_minR",
    "center_in": "image_center_in",
}

#: Size-bin edges in mm. Deliberately coarse: this spreads a reviewer's
#: attention across sizes, it is not a size distribution. Stratifying on the
#: 128 sizing bins would give about one particle per stratum and no coverage
#: statement worth having.
SIZE_EDGES = (0.0, 0.05, 0.1, 0.2, 0.4, 1.0, float("inf"))


def full_axis(name: str) -> list[str] | None:
    """Every label a stratifier can take, or ``None`` when that is unknowable.

    This is the difference between a coverage statement that can say *"this
    flight has no particle above 1 mm"* and one that can only say what it
    happened to see. ``size_bin`` has a closed vocabulary -- the edges are right
    here -- so its axis is complete and an unrepresented bin appears with a
    count of zero.

    ``reject_code`` and ``habit`` do not: their vocabularies live in
    ``calculate_reject_unified.m`` and ``holroyd.m``, and a code that no
    version emits would be a permanently empty row in every coverage statement
    ever written. For those the axis is what the flight shows, and
    :meth:`Sample.coverage` says which kind each stratifier was.
    """
    if name == "size_bin":
        out = []
        for lo, hi in zip(SIZE_EDGES[:-1], SIZE_EDGES[1:], strict=True):
            out.append(f"{lo:g}-{'inf' if hi == float('inf') else f'{hi:g}'}mm")
        return out
    return None


@dataclass(frozen=True)
class Stratum:
    """One cell of the cross-product, and what it actually yielded.

    ``available`` is what the flight holds; ``taken`` is what the sample got.
    They differ whenever a stratum is thinner than ``n_per_stratum``, and that
    difference is the coverage statement's most useful line.
    """

    key: tuple[str, ...]
    available: int
    taken: int
    indices: tuple[int, ...] = ()

    @property
    def under_filled(self) -> bool:
        """Did this stratum have less than was asked of it?"""
        return self.taken < self.requested

    #: Set by :class:`Sample` when it builds the stratum; kept as a field rather
    #: than recomputed so a stratum read back from a file is still honest.
    requested: int = 0

    def as_dict(self) -> dict:
        """The row as it is written into the queue file's coverage block.

        ``requested`` travels with ``taken`` deliberately: without it a reader
        cannot tell a stratum that was satisfied from one that was scraped
        empty, which is the single most useful thing the coverage says.
        """
        return {
            "stratum": list(self.key),
            "available": self.available,
            "requested": self.requested,
            "taken": self.taken,
            "under_filled": self.under_filled,
        }


def stratum_labels(name: str, values: np.ndarray) -> np.ndarray:
    """Turn one ``proc`` variable into per-particle stratum labels.

    Kept separate from :class:`Sample` so the labelling can be tested on arrays
    without a netCDF file anywhere near it.
    """
    values = np.asarray(values).reshape(-1)
    if name == "size_bin":
        idx = np.digitize(np.asarray(values, float), SIZE_EDGES) - 1
        out = []
        for i in idx:
            if 0 <= i < len(SIZE_EDGES) - 1:
                hi = SIZE_EDGES[i + 1]
                out.append(f"{SIZE_EDGES[i]:g}-{'inf' if hi == float('inf') else f'{hi:g}'}mm")
            else:
                # Reaches here only for a NaN or a negative diameter. Labelled
                # rather than dropped: a flight with such particles is saying
                # something, and silence would hide it.
                out.append("out-of-range")
        return np.array(out)
    if name in ("reject_code", "habit"):
        # These are stored as character codes. A value outside printable ASCII
        # is shown as its number rather than mangled into a control character.
        return np.array([chr(int(v)) if 32 <= int(v) < 127 else f"#{int(v)}"
                         for v in values])
    return np.array([str(int(v)) for v in values])


class Sample:
    """A stratified draw over one flight's ``proc`` file.

    ``by`` names strata from :data:`STRATIFIERS`; the sample is the cross-product
    of their values, ``n_per_stratum`` particles from each, drawn with a seeded
    RNG so the same arguments give the same queue on any machine.
    """

    def __init__(self, flight: str, proc_file, *, by, n_per_stratum: int,
                 seed: int = 0, only_accepted: bool = False):
        unknown = [b for b in by if b not in STRATIFIERS]
        if unknown:
            raise ValueError(
                f"unknown stratifier(s) {unknown}; known: {sorted(STRATIFIERS)}. "
                "Refused rather than ignored -- a stratifier that silently did "
                "nothing would produce a sample that is not stratified and "
                "nothing downstream could tell.")
        if not by:
            raise ValueError("`by` must name at least one stratifier")
        if n_per_stratum < 1:
            raise ValueError("n_per_stratum must be at least 1")

        self.flight = flight
        self.proc_file = Path(proc_file)
        self.by = list(by)
        self.n_per_stratum = int(n_per_stratum)
        self.seed = int(seed)
        self.only_accepted = bool(only_accepted)
        self.strata: list[Stratum] = []
        self._build()

    def _read(self):
        import netCDF4

        with netCDF4.Dataset(str(self.proc_file)) as ds:
            ds.set_auto_maskandscale(False)
            columns = {b: stratum_labels(b, ds.variables[STRATIFIERS[b]][:])
                       for b in self.by}
            n = len(next(iter(columns.values())))
            keep = np.ones(n, dtype=bool)
            if self.only_accepted:
                rej = np.asarray(ds.variables["image_auto_reject"][:]).reshape(-1)
                from .render import is_accepted_code
                keep = is_accepted_code(rej)
        return columns, keep

    def _build(self):
        columns, keep = self._read()
        n = len(keep)
        rng = random.Random(self.seed)

        # A stratifier with a closed vocabulary (`size_bin`) gets its full
        # axis, so a bin this flight has nothing in appears with a count of
        # zero -- "no particle above 1 mm" is a finding, and it is invisible if
        # the row is simply absent. One with an open vocabulary
        # (`reject_code`, `habit`) gets what the flight shows: a row for every
        # code no version emits would be permanent noise. `coverage()` records
        # which kind each was, so a reader is never left guessing whether an
        # absent stratum was empty or unaskable.
        axes = [full_axis(b) or sorted(set(columns[b].tolist())) for b in self.by]
        members: dict[tuple, list[int]] = {}
        for i in range(n):
            if not keep[i]:
                continue
            members.setdefault(tuple(columns[b][i] for b in self.by), []).append(i)

        def product(axes_):
            out = [()]
            for axis in axes_:
                out = [prev + (v,) for prev in out for v in axis]
            return out

        for key in product(axes):
            pool = members.get(key, [])
            take = sorted(rng.sample(pool, min(self.n_per_stratum, len(pool))))
            self.strata.append(Stratum(
                key=key, available=len(pool), taken=len(take),
                indices=tuple(take), requested=self.n_per_stratum))

    # ------------------------------------------------------------------ output
    @property
    def queue_name(self) -> str:
        """A default name carrying every argument that shaped the draw.

        Flight, strata, per-stratum count and seed -- so two samples of one
        flight cannot overwrite each other in a shared queue file, and so a
        name alone says how to regenerate what it points at.
        """
        return f"{self.flight}-{'+'.join(self.by)}-n{self.n_per_stratum}-s{self.seed}"

    def items(self) -> list[dict]:
        """The queue entries, in stratum order then particle order."""
        out = []
        for stratum in self.strata:
            note = ", ".join(f"{b}={v}" for b, v in zip(self.by, stratum.key, strict=True))
            for idx in stratum.indices:
                out.append({"flight": self.flight, "particle_index": int(idx),
                            "note": note})
        return out

    def coverage(self) -> dict:
        """What this sample covers, in the terms a reader will need."""
        filled = [s for s in self.strata if s.taken]
        return {
            "flight": self.flight,
            "proc_file": self.proc_file.name,
            "by": self.by,
            "n_per_stratum": self.n_per_stratum,
            "seed": self.seed,
            "only_accepted": self.only_accepted,
            "axes": {b: ("closed" if full_axis(b) else "observed") for b in self.by},
            "n_strata": len(self.strata),
            "n_strata_with_particles": len(filled),
            "n_strata_empty": sum(1 for s in self.strata if s.available == 0),
            "n_strata_under_filled": sum(1 for s in self.strata if s.under_filled),
            "n_particles": sum(s.taken for s in self.strata),
            "strata": [s.as_dict() for s in self.strata],
        }

    def write(self, path, *, queue_name: str | None = None) -> Path:
        """Write (or add to) a queue file, coverage included.

        Merges into an existing file rather than replacing it, because a
        reviewer's other queues live there and losing them to a second sample
        would be the labels-lost failure this tool's neighbours already exist to
        prevent.
        """
        path = Path(path)
        name = queue_name or self.queue_name
        data = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"{path} is not a queue file (parsed as "
                                 f"{type(data).__name__}); refusing to replace it")
        data[name] = self.items()
        coverage = data.setdefault(COVERAGE_KEY, {})
        coverage[name] = self.coverage()
        path.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        return path

    def summary(self) -> str:
        """A human-readable coverage statement, for a log or a report."""
        c = self.coverage()
        lines = [
            f"{c['n_particles']} particle(s) from {c['n_strata_with_particles']} "
            f"of {c['n_strata']} strata ({' x '.join(self.by)}), "
            f"{c['n_per_stratum']} requested each, seed {c['seed']}",
        ]
        if c["n_strata_empty"]:
            lines.append(f"  {c['n_strata_empty']} stratum/strata this flight has "
                         f"none of -- listed with a count of zero, not dropped")
        if c["n_strata_under_filled"]:
            lines.append(f"  {c['n_strata_under_filled']} stratum/strata thinner "
                         f"than {c['n_per_stratum']}; the sample took all of each")
        return "\n".join(lines)
