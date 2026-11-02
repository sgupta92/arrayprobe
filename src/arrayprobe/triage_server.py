# SPDX-License-Identifier: BSD-3-Clause
"""Mass particle visualization and triage GUI -- browse, inspect, and label
any particle in any decoded flight, at scale, locally.

Not a port stage and not an enhancement: like ``render.py`` (Track V), this
never changes a number the port computes -- it only *shows* what S2-S4
already wrote, and records a human's own opinion about it in a side file the
port never reads. That is the same test ``render.py``'s own module docstring
already applies, and the reason this lives in core `arrayprobe` rather than
`arrayprobe-enhancements`: visualization and manual labeling do not change
scientific output, so importing/running this never requires the opt-in
decision the enhancements boundary exists to gate. If a CNN classifier
(planned for `enhancements_uiops/`, not built yet) is installed, this tool will show its prediction
alongside the image as a *suggestion* -- never applied automatically, never
fed back into any port file -- through one optional, try/except import, so
`arrayprobe` itself never depends on `arrayprobe-enhancements` (enforced
project-wide by `test_no_enhancement_coupling.py`; this module adds no new
exception to that rule, it just respects it).

Verdicts are written to ``<decoded_dir>/triage_verdicts/<flight>.json`` --
plain local JSON, one file per flight, read-modify-write on every save. This
is deliberately NOT the same mechanism the earlier "Particle Triage" hosted
artifact used (browser localStorage + a hosted page's own publish() call,
which turned out to be fragile across multiple browser tabs and reload
timing). A local file on the user's own disk has none of those failure
modes: no network call, no page reload, no multi-viewer race, and it is
trivially inspectable (`cat`, `git diff`) and backed up by whatever already
backs up the rest of the repo.

Usage, from the repository root::

    .venv/Scripts/python.exe -m arrayprobe.triage_server --decoded-dir _decoded

Then open http://localhost:8765/ in a browser. ``--port`` to change the port.
"""

from __future__ import annotations

import argparse
import html
import io
import json
import math
import os
import re
import threading
import urllib.parse
from collections import OrderedDict
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import netCDF4
import numpy as np

from . import __version__, provenance
from .constants import IMGPROC_CONFIG
from .matlab_compat import HOLROYD_HABITS, REJECT_CODE_WORDS
from .render import (
    DRAWABLE_PROBES,
    crop_to_content,
    is_accepted_code,
    particle_info,
    particle_thumbnail_png,
    reconstruct_particle_image,
    unverified_placeholder_png,
)
from .triage_context import (
    LATER_SCREENS_NOTE,
    PIECE_COUNT_CLASSES,
    PIECE_COUNT_WORDS,
    PIECE_GAP_DIODES,
    MetFolder,
    StateFile,
    StateFileError,
    particle_parts,
    piece_count_class,
    reject_outcome,
    shape_test_habit,
)

__all__ = ["TriageServer", "run", "main"]

#: Probes whose file-name channel segment is the probe's own name rather than
#: an orientation split ("H"/"V") -- run_flight.channel_token()'s probetype != 2
#: branch, ``proc.<flight>.CIP.nc`` / ``<flight>.CIP.cdf`` and so on. Derived
#: from IMGPROC_CONFIG -- the one table run_flight's S2/S3 stages and
#: render.reconstruct_particle_image already both read -- rather than a second,
#: hand-maintained token list, so a probe that becomes drivable there (2DC, 2DP
#: and Fast2DC on 2026-09-20, commit 034da39) is found here with no matching
#: edit needed. "2DS" and "HVPS" are excluded: those two use the "H"/"V" SPEC
#: channel split instead, named explicitly below.
_PROBE_NAMED_CHANNELS = tuple(probe for probe in IMGPROC_CONFIG if probe not in ("2DS", "HVPS"))

_FLIGHT_RE = re.compile(
    r"^proc\.(?P<flight>.+)\.(?P<channel>H|" + "|".join(_PROBE_NAMED_CHANNELS) + r")\.nc$"
)

#: The probe each file-name channel is drawn as (``render.reconstruct_particle_image``).
#: ``.H`` covers the 2D-S and HVPS, whose framing is the same; every other
#: channel is named for its probe -- ``proc.<flight>.CIP.nc`` beside
#: ``<flight>.CIP.cdf`` -- because nothing inside a proc file says which probe
#: wrote it (2026-09-15).
_CHANNEL_PROBE = {"H": "2DS", **{probe: probe for probe in _PROBE_NAMED_CHANNELS}}

def _not_drawable_message(probe: str) -> str:
    """Why ``probe``'s particle image is not shown -- the exact unchecked
    assumption behind :data:`arrayprobe.render.DRAWABLE_PROBES`'s refusal, in
    words a reviewer reads instead of a raised ``ValueError``.

    A viewer that LISTS a flight and then raises when someone opens a
    particle is worse than one that never listed it (2026-09-20, the day 2DC/
    2DP/Fast2DC became discoverable here while ``render.py`` still refuses to
    draw two of the three). This is the text every route that would otherwise
    hit that ``ValueError`` shows in its place.
    """
    offset = IMGPROC_CONFIG[probe].image_slice_offset
    return (
        f"Particle image reconstruction is unverified for {probe}: its "
        f"image_slice_offset is {offset}, and whether that offset must also be "
        f"applied when this viewer reads the proc file's stored `position` back "
        f"(as opposed to only when imgProc_sm originally wrote it) has not been "
        f"checked against real {probe} output (arrayprobe/render.py, "
        f"DRAWABLE_PROBES). Showing a picture here could be silently wrong -- a "
        f"silhouette shifted by one slice -- so this viewer declines rather than "
        f"guess. The numeric fields for this particle (reject code, habit, "
        f"diameter, etc.) are unaffected: they come from the proc file directly, "
        f"never from this reconstruction."
    )


#: Serializes every netCDF4/HDF5 call this process makes. ThreadingHTTPServer
#: runs one thread per request, and netCDF4's underlying HDF5 C library is
#: NOT guaranteed thread-safe for concurrent opens/reads across threads on
#: this platform (the common conda HDF5 build is not compiled
#: --enable-threadsafe) -- confirmed as a real, repeated crash cause here:
#: after fixing an earlier, real-but-insufficient matplotlib.pyplot
#: thread-safety bug (commit 789c104), the server crashed again with the
#: SAME "Windows fatal exception: access violation" symptom, this time with
#: both faulted threads' last Python frame at a `netCDF4.Dataset(...)` open
#: (triage_server.py, then line 592). Every netCDF4.Dataset(...) open in this
#: module, and the one call into particle_clustering.cluster_flight (which
#: opens its own), must hold this lock for its entire duration -- not just
#: around the open -- since reads also cross into the C library.
_NC_LOCK = threading.Lock()

#: Optional CNN suggestion hook. arrayprobe NEVER depends on
#: arrayprobe-enhancements -- this import is the one place that could ever
#: reach across that boundary, and it is deliberately try/except so the
#: absence of the enhancements package (the normal case today; the model
#: itself is not built yet, see enhancements_uiops/docs/ml_accept_reject_design.md)
#: degrades to "no suggestion available" rather than an ImportError.
try:
    from arrayprobe_enhancements.ml_accept_reject import predict as _cnn_predict  # type: ignore
except ImportError:
    _cnn_predict = None

#: Optional cluster hook, same one-way-import pattern as _cnn_predict above.
#: particle_clustering.py is real new science (unsupervised ML over the
#: population) -- it lives in enhancements_uiops/; the /clusters route below only
#: renders what it returns and never changes port output, so the route
#: itself stays in core. Absence degrades to "not installed" gracefully.
try:
    from arrayprobe_enhancements.particle_clustering import (
        cluster_flight as _cluster_flight,  # type: ignore
    )
except ImportError:
    _cluster_flight = None  # type: ignore[assignment]


def _discover_flights(decoded_dir: Path, accept_unstamped: bool = False) -> dict[str, dict]:
    """flight name -> {"proc": Path, "image": Path or None, "probe": str, "stamp": Stamp|None}.

    The ``| None`` on ``image`` is real, not defensive: a decoded directory routinely holds a
    ``proc`` file whose companion decode (``<flight>.H.nc`` from v3.5, ``<flight>.H.cdf``
    from v3.1.4, :func:`_decode_path`) has been reclaimed for disk,
    and every reader below tests ``paths["image"] is None`` before opening it
    (``:454``, ``:486``, ``:563``).  The annotation said plain ``Path`` and so
    contradicted this function's own docstring; the docstring was the correct one.

    **A product whose provenance is unrecorded is refused, not indexed** (2026-09-18).
    This function used to glob ``proc.*.nc`` and index whatever matched, opening no ``.call``
    at all -- by design, and the design was wrong. That is how a *hardlink* of a CIP proc
    file, created for convenience under a second name and therefore carrying no sidecar of its
    own (a stamp is keyed by name), entered a review queue with nobody able to say which
    engine had written it; the product it pointed at had been described as v3.5 all day when
    v3.1.4 wrote it. Labels attached to a product of unknown configuration cannot be
    reattributed afterwards, so the refusal is worth more than the convenience.

    Refused entries are returned by :func:`_refused_flights` and **named on the index page**.
    A refusal nobody can see is a disappearance, which is the failure this replaces, not a
    fix for it.
    """
    flights: dict[str, dict] = {}
    for key, proc_path, channel, image_path, _state in _scan(decoded_dir):
        if not accept_unstamped and _state not in _INDEXABLE_STATES:
            continue
        flights[key] = {
            "proc": proc_path,
            "image": image_path if image_path.exists() else None,
            "probe": _CHANNEL_PROBE[channel],
            "stamp": provenance.read(proc_path),
        }
    return flights


def _written_by_html(paths: dict) -> str:
    """One muted line naming the engine and profile that wrote the proc file being labelled,
    from its ``.call`` stamp (Track V phase 3: provenance beside the numbers). A label is only
    as reattributable as this line: it says which product the verdict is about."""
    stamp = paths.get("stamp")
    engine = stamp.engine if stamp and stamp.engine else "unrecorded"
    profile = stamp.profile if stamp and stamp.profile else "unrecorded"
    return (f"<p class='muted'>written by engine <b>{html.escape(engine)}</b>, profile "
            f"<b>{html.escape(profile)}</b> (the proc file's <code>.call</code> stamp)</p>")


def _flight_overview_html(index: dict, verdicts: dict) -> str:
    """One line that answers "does this look like cloud" before any image loads (Track V
    phase 3): accepted and rejected counts, the commonest reject codes, the accepted particles'
    size quantiles, and how many particles carry a person's label. Read from the cached index,
    so it costs nothing beyond the page's own selection."""
    rc = np.asarray(index["reject_code"])
    diam = np.asarray(index["diam_minR"], dtype=float)
    acc = is_accepted_code(rc)
    n, n_acc = rc.size, int(acc.sum())
    codes, counts = np.unique(rc[~acc], return_counts=True)
    top = sorted(zip(counts.tolist(), codes.tolist(), strict=True), reverse=True)[:4]
    def label(c):
        return chr(c) if 32 < c < 127 else str(c)
    rej = ", ".join(f"{html.escape(label(c))} {k:,}" for k, c in top) or "none"
    d = diam[acc & np.isfinite(diam)]
    size = (f"accepted size median {np.median(d):.3f} mm, 90th percentile "
            f"{np.percentile(d, 90):.3f} mm" if d.size else "no accepted particles")
    human = sum(1 for v in verdicts.values() if isinstance(v, dict) and v.get("source") == "human")
    return (f"<p class='muted'>{n:,} particles: {n_acc:,} accepted, {n - n_acc:,} rejected "
            f"(commonest codes: {rej}) &middot; {size} &middot; {human:,} labelled by a person</p>")


#: The provenance states a review pass may index. ``in-flight`` is excluded with the rest: a
#: product still being written is not a thing to label, whatever its stamp will eventually say.
_INDEXABLE_STATES = ("stamped",)


def _decode_path(proc_path: Path) -> Path:
    """The decode the engine that wrote ``proc_path`` writes beside it.

    Named by :func:`arrayprobe_uiops.decode_naming.decode_path` from the proc file's own
    ``.call`` stamp, never from which file exists: a stale v3.1.4 decode left in the same
    folder must not be drawn under a v3.5 proc. The extension depends on the engine and the
    reader together (a v3.5 CIP decode comes from the shared SEA reader). A stamp that names
    no engine (a pre-2026-09-15 v3.1.4 stamp) or no stamp at all is read as v3.1.4.
    """
    # Imported here: `import arrayprobe.cli` loads this module and must not load the v3.5
    # engine (tests/test_lazy_numba_and_v35_import.py).
    from arrayprobe_uiops.decode_naming import decode_path

    return decode_path(proc_path, assume_engine="3.1.4")


def _scan(decoded_dir: Path):
    """``(key, proc_path, channel, image_path, state)`` for every ``proc.*.nc``, refused or not.

    One walk, so :func:`_discover_flights` and :func:`_refused_flights` cannot disagree about
    what is on disk or about which key a file would take -- a refusal list built by a second,
    slightly different glob would be the same class of bug as the one this exists to close.
    """
    out = []
    keys: set[str] = set()
    matched = [(m, p) for p in sorted(decoded_dir.glob("proc.*.nc"))
               if (m := _FLIGHT_RE.match(p.name))]
    # .H first, so a stem holding both a .H and a CIP proc keeps .H under the bare
    # name whatever the file names sort as.
    for m, proc_path in sorted(matched, key=lambda mp: mp[0].group("channel") != "H"):
        flight, channel = m.group("flight"), m.group("channel")
        image_path = _decode_path(proc_path)
        # A stem with both a .H and a CIP proc keeps .H under the bare name.
        key = flight if flight not in keys else f"{flight}.{channel}"
        keys.add(key)
        out.append((key, proc_path, channel, image_path, provenance.state(proc_path)))
    return out


def _refused_flights(decoded_dir: Path, accept_unstamped: bool = False) -> list[tuple[str, str]]:
    """``(file name, state)`` for every proc file :func:`_discover_flights` declined to index.

    Empty when ``accept_unstamped`` is set, because then nothing is declined.
    """
    if accept_unstamped:
        return []
    return [(proc.name, st) for _key, proc, _ch, _img, st in _scan(decoded_dir)
            if st not in _INDEXABLE_STATES]


#: What each side's rejection token means, in words.
#:
#: WHY. Author, 2026-09-16, mid-labelling-pass: *"U-imgproc_i__S-interarrival --
#: these titles should spell out what the package and code mean for each
#: category"*. A queue name is built by the SODA-2/UIOPS comparison tool as
#: ``U-<uiops reason>__S-<soda2 reasons, '.'-joined>``, which is compact for a
#: filename and unreadable for the person deciding what a particle is. Nobody
#: should have to hold a reject-code table in their head while labelling.
#:
#: SOURCES, so these are read rather than remembered. UIOOPS tokens come from
#: ``compare_soda2_uiops.uiops_reasons`` (``:78-86``) and the imgproc letters from
#: ``arrayprobe.matlab_compat.REJECT_CODES``, which cites
#: ``calculate_reject_unified.m`` line by line. SODA-2 tokens are
#: ``compare_soda2_uiops.SODA2_BITS`` (``:51``), the named bits of
#: ``soda2_reject.pro``.
#:
#: Note ``z``: on the UIOOPS side it is *sizeDist*'s area-ratio gate (0.5 in the
#: ORACLES fork, 0.2 in stock v3.1.4 and v3.5, read from the product's stamp),
#: **not** imgproc's zero-area code of the same letter. They are
#: different tests that share a character, which is exactly the sort of thing a
#: spelled-out title prevents someone from confusing at 1 a.m.
_UIOPS_REASON_TEXT = {
    "accepted": "accepted",
    "centre_in": "centre fell outside the sample area (centre-in test)",
    "S": "shattering (part of a fragment burst)",
    "z": "area ratio below sizeDist's threshold (0.5 ORACLES fork, 0.2 stock)",
    "not_filed": "never put in a second by sizeDist's walk over the airspeed rows",
    "I": "inter-arrival time too short",
    "imgproc_a": "aspect ratio outside [1/5, 5]",
    "imgproc_p": "fills less than 25 % of its bounding rectangle",
    "imgproc_s": "split image",
    "imgproc_z": "zero area",
    "imgproc_h": "hollow (no measurable hole ratio)",
    "imgproc_H": "hollow (Korolev correction applied)",
    "imgproc_u": "hollow (area-to-hole ratio too large)",
    "imgproc_A": "more than 80 % of the block shadowed",
    "imgproc_i": "side scans contradict the hollow verdict",
    "imgproc_D": "DMT depth-of-field / SPEC overload",
    "imgproc_I": "inter-arrival (from sizeDist)",
    "imgproc_R": "shattering reacceptance",
    "imgproc_S": "shattering",
}

_SODA2_REASON_TEXT = {
    "accepted": "accepted",
    "arearatio": "area ratio",
    "interarrival": "inter-arrival time",
    "size_range": "outside the accepted size range",
    "centerin": "centre outside the sample area",
    "cluster": "part of a particle cluster",
    "water": "water/liquid test",
    "irregular": "irregular shape",
    "dof": "outside the depth of field",
}


def _describe_reason(token: str, table: dict[str, str]) -> str:
    """One side's reason in words, falling back to the token when unknown.

    An unknown token is shown verbatim rather than dropped or guessed at: a new
    reject bit appearing in a queue should be visible as itself, not silently
    described as something it may not be.
    """
    parts = [table.get(t, t) for t in token.split(".") if t]
    return " + ".join(parts) if parts else token


def describe_queue(name: str) -> str:
    """``U-z__S-accepted`` -> a sentence a labeller can act on.

    Returns the name unchanged when it does not have the paired shape, so a
    hand-written queue keeps whatever title its author gave it.
    """
    if "__S-" not in name or not name.startswith("U-"):
        return name
    u_tok, _, s_tok = name[2:].partition("__S-")
    u = _describe_reason(u_tok, _UIOPS_REASON_TEXT)
    s = _describe_reason(s_tok, _SODA2_REASON_TEXT)
    u_side = "UIOPS accepts" if u_tok == "accepted" else f"UIOPS rejects: {u}"
    s_side = "SODA-2 accepts" if s_tok == "accepted" else f"SODA-2 rejects: {s}"
    return f"{u_side} · {s_side}"


#: Each Holroyd habit letter in words, keyed by the letters of
#: :data:`~arrayprobe.matlab_compat.HOLROYD_HABITS`. The words are the
#: ``holroyd_habit`` variable's own ``Description`` attribute
#: (``imgProc_sm.m:424-427``, mirrored in ``habit.py``'s docstring); ``M`` is
#: "zero image" there, not "no image". ``C`` carries no "never emitted" claim:
#: that is true of v3.1.4's stub (``holroyd.m:283-290``) and false of v3.5,
#: whose ``holroyd_new.m`` emits it, and this page shows both engines' files.
HABIT_WORDS = {
    "s": "sphere", "t": "tiny", "o": "oriented", "l": "linear",
    "h": "hexagonal", "d": "dendrite", "g": "graupel", "a": "aggregate",
    "i": "irregular", "M": "zero image", "C": "centre-out image",
}

#: A short description beside each word, shown as a tooltip. ``t``, ``o``, ``l``
#: and ``M`` are read from the branches of ``holroyd.m:45-58`` that emit them.
HABIT_HINTS = {
    "s": "round, drop-like",
    "t": "fewer than 25 shadowed pixels, too small to classify",
    "o": "elongated, tilted 30-60 degrees to the array",
    "l": "elongated, needle or column",
    "h": "plate-like outline",
    "d": "branched",
    "g": "rimed, lumpy",
    "a": "several crystals stuck together",
    "i": "no recognised shape",
    "M": "no shadowed pixels",
    "C": "centre-out image",
}

#: Habit groups for a grouped view of a queue, in display order. ``""`` stands
#: for an item whose habit is missing. Grouping is a view only: an item keeps
#: its file position, its URL and its stored label.
HABIT_GROUPS = [
    ("Round and tiny", ("s", "t")),
    ("Columns and needles", ("l", "o")),
    ("Plates and dendrites", ("h", "d")),
    ("Aggregates and graupel", ("a", "g")),
    ("Irregular", ("i",)),
    ("No shape", ("M", "C", "")),
]

#: How a stored verdict and phase read on a queue's index.
_VERDICT_WORDS = {"real": "real", "artifact": "artifact",
                  "mixed": "two particles", "unsure": "unsure"}
_PHASE_WORDS = {"ice": "ice", "drizzle": "drizzle", "unsure": "phase unsure"}

_NUM = r"(\d+(?:\.\d+)?)"
_NOTE_PARTS = [
    ("window", re.compile(r"^[a-z][a-z ]* window$")),
    ("size_bin", re.compile(rf"^{_NUM}-(\d+(?:\.\d+)?|inf)um$")),
    ("ia_us", re.compile(rf"^inter-arrival (<=|>=|<|>) {_NUM} us \({_NUM} us\)$")),
    ("minR_um", re.compile(rf"^minR {_NUM} um$")),
    ("code", re.compile(r"^code (\S+)$")),
    ("record_time", re.compile(r"^record time (\d{1,6})$")),
]
_REL_WORDS = {"<=": "≤", ">=": "≥", "<": "<", ">": ">"}


def _number(text: str) -> int | float:
    """``"83"`` -> 83, ``"0.29"`` -> 0.29: the note's own digits, never rounded."""
    return int(text) if text.isdigit() else float(text)


def reject_code_words(code: str) -> str | None:
    """A UIOOPS reject letter in words, or ``None`` for a letter no table names.

    ``REJECT_CODE_WORDS`` first; ``_UIOPS_REASON_TEXT``'s ``imgproc_*`` rows only
    for a letter it lacks. ``H``/``h`` are the two hollow verdicts, never a habit.
    """
    return REJECT_CODE_WORDS.get(code) or _UIOPS_REASON_TEXT.get(f"imgproc_{code}")


def parse_note(note: str) -> dict:
    """A queue item's machine note as named fields, for display only.

    ``"cold window, 55-100um, minR 83 um, code H, record time 142221"`` gives
    ``window``, ``size_bin`` ("55–100 µm"), ``minR_um`` (83), ``code`` ("H", the
    automatic reject code), ``record_time`` ("14:22:21 UTC") and ``text`` (the
    note itself). An ``inter-arrival <= 1 us (0.29 us)`` part gives ``ia_us``
    (0.29) and ``ia_rule`` ("≤ 1 µs").

    Fails closed: a note with any part these patterns do not recognise, or with
    one field twice, comes back as ``{"text": note}``, so nothing in it is
    dropped or guessed at.
    """
    if not isinstance(note, str) or not note.strip():
        return {"text": note}
    out: dict = {}
    for part in (p.strip() for p in note.split(",")):
        for field, pattern in _NOTE_PARTS:
            m = pattern.match(part)
            if m is None:
                continue
            if field in out:
                return {"text": note}
            if field == "window":
                out["window"] = part
            elif field == "size_bin":
                lo, hi = m.group(1), m.group(2)
                out["size_bin"] = f"≥ {lo} µm" if hi == "inf" else f"{lo}–{hi} µm"
            elif field == "ia_us":
                out["ia_rule"] = f"{_REL_WORDS[m.group(1)]} {m.group(2)} µs"
                out["ia_us"] = _number(m.group(3))
            elif field == "minR_um":
                out["minR_um"] = _number(m.group(1))
            elif field == "code":
                out["code"] = m.group(1)
            else:
                hhmmss = m.group(1).zfill(6)
                out["record_time"] = f"{hhmmss[:2]}:{hhmmss[2:4]}:{hhmmss[4:]} UTC"
            break
        else:
            return {"text": note}
    out["text"] = note
    return out


def _word_and_letter(word: str | None, letter, hint: str | None = None) -> str:
    """``word <small>letter</small>``; an unknown letter is shown as itself."""
    if letter is None or letter == "":
        return "<span class='muted'>—</span>"
    letter_html = f"<small class='muted'>{html.escape(str(letter))}</small>"
    if not word:
        return letter_html
    title = f" title='{html.escape(hint)}'" if hint else ""
    return f"<span{title}>{html.escape(word)}</span> {letter_html}"


def habit_html(letter) -> str:
    """A Holroyd habit letter as its word with the letter in small type."""
    return _word_and_letter(HABIT_WORDS.get(letter), letter, HABIT_HINTS.get(letter))


def reject_code_html(code) -> str:
    """A reject code as its words with the letter in small type."""
    words = reject_code_words(code) if isinstance(code, str) else None
    return _word_and_letter(words, code)


#: Each per-particle property beside the image: variable name -> (long name, unit, format).
#: Read from the writer: ``imgproc.py``'s ``_VARIABLES`` and the ``put`` lines that fill
#: them. ``image_area`` is mm² (``put`` multiplies the pixel count by the diode size
#: squared). ``percent_shadow_area`` is a fraction, neither a percent nor a share of the
#: L×W box, whatever its ``Units``/``Description`` attributes say: ``imgProc_sm.m``
#: overwrites it with the area over the circle whose diameter is the longer of length and
#: width (``imgproc.py``'s ``acc.percent_shadow`` lines; v3.5's ``_percent_shadow``).
#: ``image_touching_edge`` holds ``touching_edge - '0'``: 0, 68 (``'t'``) or -48.
#: Display only: no stored number changes, and the stored value stays in the row's tooltip.
PROPERTY_NAMES = {
    "particle_index": ("Particle index in the file", "", "int"),
    "parent_rec_num": ("Record number", "", "int"),
    "particle_num": ("Particle number within the record", "", "int"),
    "image_width": ("Width across the array", "diodes", "int"),
    "image_length": ("Length along the flight", "slices", "int"),
    "reject_code": ("Automatic reject code", "", "reject"),
    "reject_outcome": ("What the reject code did", "", "outcome"),
    "shape_habit": ("Holroyd shape test, re-run on this image", "", "habit"),
    "habit_code": ("Holroyd habit written in the file", "", "habit"),
    "parts": ("Separate pieces of shadow", "", "parts"),
    "air_temperature": ("Air temperature at the record's second", "°C", "temp"),
    "diam_minR": ("Smallest enclosing circle", "µm", "um_from_mm"),
    "image_area": ("Shadowed area", "mm²", "sig3"),
    "image_hollow": ("Hollow flag", "", "yes_no"),
    "area_hole_ratio": ("Area-to-hole ratio", "", "sig3"),
    "image_axis_ratio": ("Axis ratio", "", "sig3"),
    "percent_shadow_area": ("Shadowed share of the circle across the longer side",
                            "fraction", "sig3"),
    "image_touching_edge": ("Touches the array edge", "", "edge"),
}

_EDGE_WORDS = {0: "no", 68: "yes", -48: "no slices"}
_YES_NO_WORDS = {0: "no", 1: "yes"}


def _sig3(x: float) -> str:
    """``x`` to three significant figures, in plain notation (``1230``, never ``1.23e+03``)."""
    if x == 0:
        return "0"
    decimals = 2 - math.floor(math.log10(abs(x)))
    rounded = round(x, decimals)
    return f"{rounded:.0f}" if decimals <= 0 else f"{rounded:.{decimals}f}"


def _plain(v) -> str:
    """A value as it reads: a whole float without its ``.0``."""
    if isinstance(v, float) and math.isfinite(v) and v.is_integer():
        return str(int(v))
    return str(v)


def _property_value_html(v, unit: str, fmt: str) -> str:
    """One property's value for display; the stored number itself is never changed."""
    if fmt == "reject":
        return reject_code_html(v)
    if fmt == "habit":
        return habit_html(v)
    if fmt == "outcome":
        if not v:
            return "<span class='muted'>—</span>"
        kind, words = v
        return (f"<span class='outcome o-{html.escape(kind)}'>{html.escape(words)}</span>"
                f"<br><small class='muted'>{html.escape(LATER_SCREENS_NOTE)}</small>")
    if fmt == "parts":
        if not v:
            return "<span class='muted'>none</span>"
        n = int(v)
        if n == 1:
            return "1"
        return (f"{n} <small class='muted'>(numbered on the image, in order along the "
                "flight)</small>")
    if fmt == "temp":
        if not isinstance(v, dict):
            return "<span class='muted'>—</span>"
        if v.get("degC") is None:
            return f"<span class='muted'>not available: {html.escape(v.get('why', ''))}</span>"
        return (f"{v['degC']:.1f} °C <small class='muted'>({html.escape(v.get('source', ''))}, "
                f"ambient_temp at {html.escape(v.get('at', ''))} UTC)</small>")
    if v is None:
        return "<span class='muted'>—</span>"
    if isinstance(v, float) and math.isnan(v):
        return "<span class='muted'>not a number</span>"
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return html.escape(str(v))
    unit_html = f" {html.escape(unit)}" if unit else ""
    if fmt in ("edge", "yes_no") and float(v).is_integer():
        words = (_EDGE_WORDS if fmt == "edge" else _YES_NO_WORDS).get(int(v))
        if words:
            return f"{words} <small class='muted'>{int(v)}</small>"
    if fmt == "um_from_mm" and math.isfinite(v):
        return f"{_sig3(1000 * v)}{unit_html} <small class='muted'>({_sig3(v)} mm)</small>"
    if fmt == "sig3" and math.isfinite(v):
        return f"{_sig3(v)}{unit_html}"
    return f"{html.escape(_plain(v))}{unit_html}"


def _kv_html(info: dict) -> str:
    """The property rows beside a particle image: long name and unit, with the variable
    name in small type beside it. A property not in :data:`PROPERTY_NAMES` still shows,
    under its variable name."""
    rows = []
    for name, v in info.items():
        long_name, unit, fmt = PROPERTY_NAMES.get(name, (None, "", ""))
        var = f"<small class=var>{html.escape(str(name))}</small>"
        label = f"{html.escape(long_name)} {var}" if long_name else var
        title = ""  # the unrounded stored number, where the display rounds it
        if isinstance(v, float) and not (math.isfinite(v) and v.is_integer()):
            stored = f"{v!r}{' mm' if fmt == 'um_from_mm' else ''}"
            title = f" title='stored value {html.escape(stored)}'"
        rows.append(f"<div{title}><b>{label}</b>{_property_value_html(v, unit, fmt)}</div>")
    return "".join(rows)


#: The first property row that goes below the image rather than beside it: the reject
#: outcome, which carries the size-distribution note, and every row after it (author,
#: 2026-10-02), so the column beside the image is short and the space under the
#: image is used.
_BELOW_IMAGE_FROM = "reject_outcome"


def _kv_split_html(info: dict) -> tuple[str, str]:
    """``(beside, below)``: :func:`_kv_html` of ``info`` cut before
    :data:`_BELOW_IMAGE_FROM`; every row is in one of the two, in order. Without that row,
    everything is beside the image."""
    keys = list(info)
    if _BELOW_IMAGE_FROM not in keys:
        return _kv_html(info), ""
    cut = keys.index(_BELOW_IMAGE_FROM)
    return (_kv_html({k: info[k] for k in keys[:cut]}),
            _kv_html({k: info[k] for k in keys[cut:]}))


def _particle_extras(paths: dict, idx: int, met: MetFolder | None,
                     gap: int = PIECE_GAP_DIODES) -> tuple[dict, list[dict]]:
    """What the particle page adds beside the product's own values, and the pieces.

    Returns ``(extras, parts)``: ``extras`` holds ``shape_habit`` (Holroyd's shape test re-run
    on the image; ``None`` when the probe is not drawable or the image file is missing),
    ``parts`` (how many separate pieces of shadow) and ``air_temperature`` (a dict for the
    ``temp`` format: ``degC`` or ``why``). Nothing here is written anywhere.
    """
    probe = paths.get("probe", "2DS")
    extras: dict = {"shape_habit": None, "parts": None}
    parts: list[dict] = []
    image = paths.get("image")
    with _NC_LOCK, netCDF4.Dataset(paths["proc"]) as proc_ds:
        date = (int(proc_ds.variables["Date"][idx]) if "Date" in proc_ds.variables else None)
        hms = (int(proc_ds.variables["Time"][idx]) if "Time" in proc_ds.variables else None)
        extras["record"] = _record_context(proc_ds, idx, _tas_csv_of(paths["proc"]))
        if probe in DRAWABLE_PROBES and image and Path(image).is_file():
            with netCDF4.Dataset(image) as img_ds:
                c = reconstruct_particle_image(img_ds, proc_ds, idx, probe=probe)
            extras["shape_habit"] = shape_test_habit(c, IMGPROC_CONFIG[probe].ds)
            parts = particle_parts(c, gap=gap)
            extras["parts"] = len(parts)
    at = f"{hms // 10000:02d}:{hms // 100 % 100:02d}:{hms % 100:02d}" if hms is not None else ""
    if met is None:
        extras["air_temperature"] = {
            "degC": None,
            "why": "name a state-variable file on the index page, or start the server with "
                   "--state-file <file> or --met-dir <folder of ARM or ORACLES merged files>"}
    else:
        hit = met.temperature_at(date, hms) if date is not None and hms is not None else None
        extras["air_temperature"] = (
            {"degC": hit[0], "source": hit[1], "at": at} if hit else
            {"degC": None, "why": f"no valid {met.VARIABLE} at {at or 'this time'} UTC in "
                                  f"{met.folder}"})
    return extras, parts


def _info_with_extras(info: dict, extras: dict) -> dict:
    """``info`` with the extras placed beside the values they explain: the outcome after the
    reject code, the re-run shape test before the file's habit letter, the rest at the end."""
    out: dict = {}
    for key, value in info.items():
        if key == "habit_code" and "shape_habit" in extras:
            out["shape_habit"] = extras["shape_habit"]
        out[key] = value
        if key == "reject_code":
            out["reject_outcome"] = reject_outcome(value)
    for key in ("parts", "air_temperature"):
        if key in extras:
            out[key] = extras[key]
    return out


#: Above a queue's table when any of its notes parse (``parse_note``).
_QUEUE_LEGEND = (
    "Reject code: what the automatic screen said about this particle (H/h = hollow, "
    "accepted here). Smallest circle: diameter of the smallest circle enclosing the "
    "shadow. Habit: the Holroyd shape class from the shape test re-run on each image (a "
    "UIOPS v3.5 file writes 's' for any small particle with an open centre, whatever its "
    "shape); see the field guide below."
)


def _field_guide_html() -> str:
    """The habit words, one line per group, at the top of a queue's page: open, and one
    click on its summary folds it away so the table is a short scroll."""
    rows = []
    for group, letters in HABIT_GROUPS:
        named = [c for c in letters if c in HOLROYD_HABITS]
        items = "; ".join(f"{habit_html(c)} ({html.escape(HABIT_HINTS[c])})" for c in named)
        rows.append(f"<li><b>{html.escape(group)}</b>: {items}</li>")
    return ("<details id='field-guide' open><summary>Field guide: the Holroyd habits</summary>"
            f"<ul>{''.join(rows)}</ul></details>")


#: A stored ``holroyd_habit`` value back to its letter (the inverse of
#: :data:`~arrayprobe.matlab_compat.HOLROYD_HABITS`, as ``render.particle_info`` reads it).
_HABIT_BY_CODE = {code: letter for letter, code in HOLROYD_HABITS.items()}
#: Each letter's group rank in :data:`HABIT_GROUPS`; a missing or unknown habit
#: falls in the last group, "No shape".
_HABIT_RANK = {c: rank for rank, (_, letters) in enumerate(HABIT_GROUPS) for c in letters}
_NO_SHAPE_RANK = len(HABIT_GROUPS) - 1
#: ``?order=`` values a queue's pages accept; the first is the default.
QUEUE_ORDERS = ("habit", "file")
#: ``name -> (items, product stamp, habits)``; valid while the queue's item list is the
#: same object and no product it reads has changed on disk.
_QUEUE_HABITS_CACHE: dict[str, tuple] = {}
_QUEUE_PIECES_CACHE: dict[str, tuple] = {}


def _mtime_ns(path) -> int | None:
    try:
        return os.stat(path).st_mtime_ns
    except (OSError, TypeError):
        return None


def _read_habit_letters(proc_path, indices: list[int]) -> dict[int, str]:
    """``{particle_index: habit letter}`` from one product, in one open; a particle
    whose stored value is zero, masked or not a habit is left out."""
    with _NC_LOCK, netCDF4.Dataset(proc_path) as ds:
        var = ds.variables.get("holroyd_habit")
        if var is None:
            return {}
        n = var.shape[0]
        wanted = [i for i in indices if 0 <= i < n]
        if not wanted:
            return {}
        values = np.ravel(np.ma.filled(np.ma.asarray(var[wanted], dtype=float), np.nan))
    out = {}
    for i, v in zip(wanted, values, strict=True):
        letter = _HABIT_BY_CODE.get(int(v)) if np.isfinite(v) else None
        if letter:
            out[i] = letter
    return out


def _shape_letters(paths: dict, indices: list[int]) -> dict[int, str]:
    """``{particle_index: letter}`` from Holroyd's shape test re-run on each particle's image
    (:func:`triage_context.shape_test_habit`), one open of the image and proc files; ``{}``
    when the probe is not drawable or the image file is missing. 0.031 s per particle on the
    2018-02-15 ARM flight (measured 2026-10-01, 200 particles)."""
    probe = paths.get("probe", "2DS")
    image = paths.get("image")
    if probe not in DRAWABLE_PROBES or not image or not Path(image).is_file():
        return {}
    out: dict[int, str] = {}
    ds_mm = IMGPROC_CONFIG[probe].ds
    with _NC_LOCK, netCDF4.Dataset(paths["proc"]) as proc_ds, netCDF4.Dataset(image) as img_ds:
        n = proc_ds.variables["parent_rec_num"].shape[0]
        for i in indices:
            if 0 <= i < n:
                c = reconstruct_particle_image(img_ds, proc_ds, i, probe=probe)
                out[i] = shape_test_habit(c, ds_mm)
    return out


def _piece_counts(paths: dict, indices: list[int]) -> dict[int, int]:
    """``{particle_index: number of separate shadow pieces}``, counted with the particle page's
    own rule (:func:`triage_context.particle_parts` at :data:`PIECE_GAP_DIODES`), one open of
    the image and proc files; ``{}`` when the probe is not drawable or the image is missing.
    Display only, the two-piece count shown up front: it never changes a computed number."""
    probe = paths.get("probe", "2DS")
    image = paths.get("image")
    if probe not in DRAWABLE_PROBES or not image or not Path(image).is_file():
        return {}
    out: dict[int, int] = {}
    with _NC_LOCK, netCDF4.Dataset(paths["proc"]) as proc_ds, netCDF4.Dataset(image) as img_ds:
        n = proc_ds.variables["parent_rec_num"].shape[0]
        for i in indices:
            if 0 <= i < n:
                c = reconstruct_particle_image(img_ds, proc_ds, i, probe=probe)
                out[i] = len(particle_parts(c))
    return out


def _queue_pieces(name: str, items: list[dict], flights: dict[str, dict]) -> list[int | None]:
    """Each queue item's piece count (:func:`_piece_counts`), ``None`` where no image can be
    drawn. Cached per queue on the same stamp as :func:`_queue_habits`."""
    resolved = [_resolve_queue_flight(it.get("flight"), flights) for it in items]
    procs = {f: flights[f].get("proc") for f in set(resolved) if f is not None}
    stamp = tuple(sorted((f, str(p), _mtime_ns(p)) for f, p in procs.items()))
    hit = _QUEUE_PIECES_CACHE.get(name)
    if hit is not None and hit[0] is items and hit[1] == stamp:
        return hit[2]
    pieces: list[int | None] = [None] * len(items)
    positions: dict[str, list[int]] = {}
    for pos, f in enumerate(resolved):
        if f is not None and procs.get(f) is not None:
            positions.setdefault(f, []).append(pos)
    for f, where in positions.items():
        wanted = sorted({int(items[p]["particle_index"]) for p in where})
        counts = _piece_counts(flights[f], wanted)
        for p in where:
            pieces[p] = counts.get(int(items[p]["particle_index"]))
    _QUEUE_PIECES_CACHE[name] = (items, stamp, pieces)
    return pieces


def pieces_filter(qs: dict) -> int | None:
    """The ``pieces`` query value as a count of at least 1 (``2`` means two or more pieces,
    ``1`` exactly one), or ``None`` when absent or not a positive integer."""
    raw = (qs.get("pieces") or [None])[0]
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None


def keep_by_pieces(view: list[int], pieces: list[int | None], want: int | None) -> list[int]:
    """``view`` narrowed to the positions whose piece count matches ``want``: ``1`` keeps
    one-piece images, ``2`` or more keeps images of at least that many pieces; ``None``
    keeps everything. An item with no count is kept only when there is no filter."""
    if want is None:
        return view
    if want == 1:
        return [i for i in view if pieces[i] == 1]
    return [i for i in view if (n := pieces[i]) is not None and n >= want]


def keep_page_by_pieces(page_idx: list[int], counts: dict[int, int],
                        want: int | None) -> list[int]:
    """The particle indices of one flight page narrowed by :func:`keep_by_pieces`, with
    ``counts`` as :func:`_piece_counts` returns it. Display only."""
    pieces = [counts.get(int(i)) for i in page_idx]
    return [page_idx[p] for p in keep_by_pieces(list(range(len(page_idx))), pieces, want)]


_QUEUE_COUNT_CACHE: dict[str, tuple] = {}
_COUNT_SHORT = {"one": "1", "two": "2", "three_or_more": "3+"}


def _count_classes(paths: dict, indices: list[int]) -> dict[int, str]:
    """``{particle_index: piece-count class}`` (:func:`triage_context.piece_count_class`, the
    size-scaled gap), one open of the image and proc files; ``{}`` when the probe is not
    drawable or the image is missing. Display only: it never changes a computed number."""
    probe = paths.get("probe", "2DS")
    image = paths.get("image")
    if probe not in DRAWABLE_PROBES or not image or not Path(image).is_file():
        return {}
    out: dict[int, str] = {}
    with _NC_LOCK, netCDF4.Dataset(paths["proc"]) as proc_ds, netCDF4.Dataset(image) as img_ds:
        n = proc_ds.variables["parent_rec_num"].shape[0]
        for i in indices:
            if 0 <= i < n:
                cls = piece_count_class(reconstruct_particle_image(img_ds, proc_ds, i,
                                                                   probe=probe))
                if cls is not None:
                    out[i] = cls
    return out


def _queue_count_classes(name: str, items: list[dict],
                         flights: dict[str, dict]) -> list[str | None]:
    """Each queue item's piece-count class (:func:`_count_classes`), ``None`` where no image can
    be drawn. Cached per queue on the same stamp as :func:`_queue_pieces`."""
    resolved = [_resolve_queue_flight(it.get("flight"), flights) for it in items]
    procs = {f: flights[f].get("proc") for f in set(resolved) if f is not None}
    stamp = tuple(sorted((f, str(p), _mtime_ns(p)) for f, p in procs.items()))
    hit = _QUEUE_COUNT_CACHE.get(name)
    if hit is not None and hit[0] is items and hit[1] == stamp:
        return hit[2]
    classes: list[str | None] = [None] * len(items)
    positions: dict[str, list[int]] = {}
    for pos, f in enumerate(resolved):
        if f is not None and procs.get(f) is not None:
            positions.setdefault(f, []).append(pos)
    for f, where in positions.items():
        wanted = sorted({int(items[p]["particle_index"]) for p in where})
        got = _count_classes(flights[f], wanted)
        for p in where:
            classes[p] = got.get(int(items[p]["particle_index"]))
    _QUEUE_COUNT_CACHE[name] = (items, stamp, classes)
    return classes


def count_filter(qs: dict) -> str | None:
    """The ``count`` query value when it is one of :data:`PIECE_COUNT_CLASSES`
    (``one``, ``two``, ``three_or_more``), else ``None``."""
    raw = (qs.get("count") or [None])[0]
    return raw if raw in PIECE_COUNT_CLASSES else None


def keep_by_count(view: list[int], classes: list[str | None], want: str | None) -> list[int]:
    """``view`` narrowed to the positions whose piece-count class is ``want``; ``None`` keeps
    everything, and an item with no class is kept only when there is no filter."""
    if want is None:
        return view
    return [i for i in view if classes[i] == want]


def count_class_html(cls: str | None) -> str:
    """A piece-count class as ``1`` / ``2`` / ``3+`` with its words on hover; a dash for none."""
    if cls is None:
        return "<span class='muted'>—</span>"
    return (f"<span class='count-class' title='{html.escape(PIECE_COUNT_WORDS[cls])}'>"
            f"{_COUNT_SHORT[cls]}</span>")


def count_filter_bar(base: str, want: str | None) -> str:
    """Links narrowing ``base`` to one piece-count class, the current one in bold."""
    sep = "&" if "?" in base else "?"
    links = []
    for cls in PIECE_COUNT_CLASSES:
        lab = html.escape(PIECE_COUNT_WORDS[cls])
        links.append(f"<b>{lab}</b>" if want == cls
                     else f"<a href='{base}{sep}count={cls}'>{lab}</a>")
    return "particles per image: " + " · ".join(links)


def piece_label_agreement(verdicts: dict, counts: dict[int, int]) -> dict[str, int]:
    """How the reviewer's labels agree with the piece count (gap fixed at
    :data:`PIECE_GAP_DIODES`). Display only; it never changes a computed number.

    The two-particle label is the verdict ``"mixed"``, whose button reads "Two particles".
    ``verdicts`` is a flight's sidecar (``{str(index): {"verdict": ...}}``), ``counts`` is
    :func:`_piece_counts` over those indices; a labelled particle with no count (no image)
    is counted as labelled only. Returns ``labelled``, ``multi`` (labelled with two or more
    pieces), ``multi_two`` (of those, labelled two particles), ``two`` (two-particle labels)
    and ``two_multi`` (of those, with two or more pieces)."""
    out = {"labelled": 0, "multi": 0, "multi_two": 0, "two": 0, "two_multi": 0}
    for key, rec in verdicts.items():
        if not isinstance(rec, dict) or rec.get("verdict") not in VALID_VERDICTS:
            continue
        try:
            idx = int(key)
        except (TypeError, ValueError):
            continue
        out["labelled"] += 1
        multi = (counts.get(idx) or 0) >= 2
        two = rec.get("verdict") == "mixed"
        out["multi"] += multi
        out["multi_two"] += multi and two
        out["two"] += two
        out["two_multi"] += two and multi
    return out


def piece_agreement_html(a: dict[str, int]) -> str:
    """One line stating :func:`piece_label_agreement`'s counts."""
    if not a.get("labelled"):
        return "<p class='muted'>Pieces against labels: no labelled particles yet.</p>"
    return (f"<p class='muted'>Pieces against labels: of {a['labelled']:,} labelled, "
            f"{a['multi']:,} have two or more pieces and {a['multi_two']:,} of those are "
            f"labelled two particles; {a['two_multi']:,} of {a['two']:,} two-particle "
            f"labels have two or more pieces.</p>")


def _queue_habits(name: str, items: list[dict], flights: dict[str, dict]) -> list[str]:
    """Each queue item's Holroyd habit letter from the shape test re-run on its image
    (the product's own letter where the image cannot be drawn), ``""`` if none.

    Read lazily, on the first page of the queue that needs it, and cached per queue:
    one netCDF open per flight, never one per item and never at startup. An item the
    product gives no habit for keeps the ``habit`` its queue entry carries, if any.
    """
    resolved = [_resolve_queue_flight(it.get("flight"), flights) for it in items]
    procs = {f: flights[f].get("proc") for f in set(resolved) if f is not None}
    stamp = tuple(sorted((f, str(p), _mtime_ns(p)) for f, p in procs.items()))
    hit = _QUEUE_HABITS_CACHE.get(name)
    if hit is not None and hit[0] is items and hit[1] == stamp:
        return hit[2]
    positions: dict[str, list[int]] = {}
    for pos, f in enumerate(resolved):
        if f is not None and procs.get(f) is not None:
            positions.setdefault(f, []).append(pos)
    habits = [""] * len(items)
    for f, where in positions.items():
        wanted = sorted({int(items[p]["particle_index"]) for p in where})
        # Holroyd's shape test re-run on each image: the letter a v3.5 file stores is
        # 's' for any small particle with an open centre, whatever its shape. The file's own
        # letter is the fallback when the image cannot be drawn.
        # A blank image ('M') says nothing about shape, so the file's letter stands there.
        letters = _read_habit_letters(procs[f], wanted)
        letters.update({i: h for i, h in _shape_letters(flights[f], wanted).items() if h != "M"})
        for p in where:
            habits[p] = letters.get(int(items[p]["particle_index"]), "")
    for pos, item in enumerate(items):
        if not habits[pos] and item.get("habit") in HOLROYD_HABITS:
            habits[pos] = item["habit"]
    _QUEUE_HABITS_CACHE[name] = (items, stamp, habits)
    return habits


def _queue_order(habits: list[str], order: str) -> list[int]:
    """The file positions in viewing order.

    ``"file"`` is the queue's own order, which is the random draw. ``"habit"``
    groups similar habits in :data:`HABIT_GROUPS` order and keeps file order
    inside each group, so the draw survives within a group. Either way a
    position is an item's identity: its URL and its stored label never move.
    """
    if order == "file":
        return list(range(len(habits)))
    return sorted(range(len(habits)),
                  key=lambda p: (_HABIT_RANK.get(habits[p], _NO_SHAPE_RANK), p))


def _order_query(order: str) -> str:
    """The query string that keeps a non-default order across links."""
    return "" if order == QUEUE_ORDERS[0] else f"?order={order}"


#: A queue summary's verdict counts in the order the bar and the text show them:
#: (key, words). The bar's colour for each is the class ``s-<key>`` in ``STYLE``,
#: the colour a labelled card of that verdict already carries. ``other`` (a stored
#: verdict this version does not know) is shown only when there is one.
_SUMMARY_VERDICTS = (("real", "real"), ("artifact", "artifact"),
                     ("mixed", "two particles"), ("unsure", "unsure"),
                     ("other", "other"), ("left", "left"))
#: A queue summary's phase counts, in order: (key, words). ``not_set`` covers every
#: item without a phase, labelled or not, so the phase counts add up to the queue.
_SUMMARY_PHASES = (("ice", "ice"), ("drizzle", "drizzle"),
                   ("unsure", "phase unsure"), ("not_set", "not set"))


def _queue_summary(name: str, items: list[dict], flights: dict[str, dict],
                   verdicts_for) -> dict:
    """How a queue's items are labelled: verdict and phase counts, one place.

    ``verdicts_for(name, flight)`` is the lookup the queue pages use
    (``TriageServer._queue_verdicts``), so a blind re-check queue counts only its
    own labels. Each item's flight is resolved the way the particle page resolves
    it; an unresolved flight, or a verdict store that cannot be read, counts its
    items as left rather than failing the page. Returns ``{"n", "labelled",
    "verdicts": {real, artifact, mixed, unsure, other, left}, "phases": {ice,
    drizzle, unsure, not_set}}``.

    Before 2026-09-16 the counter looked up the queue's raw flight name: the
    ACE-ENA queue names ``base170707102822.H`` while its verdicts are stored under
    the resolved ``base170707102822``, so it opened no file and reported ``0 / 20``
    to a reviewer who had just labelled twenty particles.
    """
    verdicts = {key: 0 for key, _ in _SUMMARY_VERDICTS}
    phases = {key: 0 for key, _ in _SUMMARY_PHASES}
    by_flight: dict[str, list[dict]] = {}
    for item in items:
        resolved = _resolve_queue_flight(item.get("flight"), flights)
        if resolved is not None:
            by_flight.setdefault(resolved, []).append(item)
    for flight, flight_items in by_flight.items():
        try:
            stored = verdicts_for(name, flight)
        except VerdictStoreError:
            continue
        for item in flight_items:
            record = stored.get(str(item["particle_index"]))
            if record is None:
                continue
            v = record.get("verdict") if isinstance(record, dict) else None
            verdicts[v if v in VALID_VERDICTS else "other"] += 1
            p = record.get("phase") if isinstance(record, dict) else None
            if p in VALID_PHASES:
                phases[p] += 1
    n = len(items)
    labelled = sum(verdicts.values())
    verdicts["left"] = n - labelled
    phases["not_set"] = n - phases["ice"] - phases["drizzle"] - phases["unsure"]
    return {"n": n, "labelled": labelled, "verdicts": verdicts, "phases": phases}


def _queue_summary_text(summary: dict) -> str:
    """The summary in words, e.g. ``2 real · 1 artifact · … · 1 left; phase 1 ice · …``."""
    v, p = summary["verdicts"], summary["phases"]
    verdict_part = " · ".join(f"{v[key]} {words}" for key, words in _SUMMARY_VERDICTS
                              if key != "other" or v[key])
    phase_part = " · ".join(f"{p[key]} {words}" for key, words in _SUMMARY_PHASES)
    return f"{verdict_part}; phase {phase_part}"


def _queue_summary_html(summary: dict) -> str:
    """A stacked bar of the verdict counts (verdict colours, in order) and the text below it.

    Each segment's width is its share of the queue and its ``title`` names the count
    and the share, so the bar reads on hover as well as at a glance.
    """
    n = summary["n"]
    text = _queue_summary_text(summary)
    segments = []
    for key, words in _SUMMARY_VERDICTS:
        count = summary["verdicts"][key]
        if not count:
            continue
        share = 100 * count / n
        segments.append(
            f"<span class='s-{key}' style='width:{share:.2f}%' "
            f"title='{count} {html.escape(words)} ({share:.1f}% of {n})'></span>")
    return (f"<div class='qsum'><div class='sbar' role='img' "
            f"aria-label='{html.escape(text)}'>{''.join(segments)}</div>"
            f"<div class='qsum-text'>{html.escape(text)}</div></div>")


def _resolve_queue_flight(name, flights: dict[str, dict]) -> str | None:
    """Map a queue item's flight name onto a discovered flight key, or ``None``.

    WHY THIS EXISTS. :func:`_discover_flights` gives the **bare** stem to whichever
    channel wins (``.H`` first), so a directory holding both channels of
    ``base170707102822`` yields the keys ``base170707102822`` and
    ``base170707102822.V`` -- and **never** ``base170707102822.H``. A queue built
    naming the channel explicitly therefore resolves to nothing, and every item in
    it renders "unknown flight" while the index happily lists the flight one line
    above. Measured 2026-09-16 on the ACE-ENA 07-07 queue, whose items all say
    ``base170707102822.H``.

    Rather than rewrite the queue file -- the same mismatch would come back with
    the next queue a comparison script writes -- the lookup accepts
    the explicit form when, and only when, dropping the channel lands on a real
    flight whose own channel is the one that was asked for. An arbitrary suffix is
    still refused, so a genuinely wrong name still fails loudly instead of being
    silently mapped onto a neighbouring flight.
    """
    if not isinstance(name, str):
        return None
    if name in flights:
        return name
    stem, _, channel = name.rpartition(".")
    if stem and channel and stem in flights:
        probe = flights[stem].get("probe")
        if _CHANNEL_PROBE.get(channel) == probe:
            return stem
    return None


#: The only values any verdict button on any page actually sends. A POST body's
#: "verdict" is otherwise free-form attacker-reachable text that gets written to the
#: sidecar JSON and later interpolated into an HTML class attribute / badge -- validate
#: here rather than trust the client, since a browser tab open on this origin (or any
#: local process) can POST directly without going through the rendered buttons at all.
#:
#: ``"mixed"`` is the fourth label the taxonomy lacked
#: (``ml_accept_reject_design.md:109``): two particles in one image, which is
#: neither an artifact nor a clean single particle, and which a reviewer
#: previously had to record as ``"unsure"`` -- collapsing a real category into
#: the "I could not tell" bucket and quietly poisoning both.
VALID_VERDICTS = frozenset({"artifact", "real", "unsure", "mixed"})

#: The single key that records each verdict, for keyboard labelling (author
#: request, 2026-09-16: a pass is hundreds of particles and the mouse is the
#: cost). Chosen as the verdict's own initial where that is free -- ``mixed``
#: takes ``t`` for "two particles", the wording already on its button, because
#: ``m`` reads as nothing and the button does not say "mixed".
#:
#: Every verdict must appear here: ``_verdict_widget`` looks each one up while
#: building its button, so adding a verdict without a key raises at render time
#: rather than silently shipping a button no key reaches.
#: ``tests/test_verdict_keyboard.py`` asserts the two sets agree.
_VERDICT_KEYS = {"artifact": "a", "real": "r", "mixed": "t", "unsure": "u"}

#: A particle's phase, recorded beside its verdict: the reviewer decides ice or
#: drizzle per particle while looking at the image.
#: It is a second, optional field of the same record, not a fifth verdict --
#: "real" says the image is a particle, the phase says what kind -- so a record
#: without ``phase``, which is every record written before it existed, reads
#: exactly as it did. ``unsure`` here means the reviewer could not tell the
#: phase, which is a different statement from the verdict ``unsure``.
VALID_PHASES = frozenset({"ice", "drizzle", "unsure"})

#: One key per phase, disjoint from :data:`_VERDICT_KEYS` and from the ``n``/``p``
#: navigation keys (``tests/test_triage_phase.py`` asserts both). ``q`` is the
#: question mark's key for "phase unsure", because ``u`` is the verdict's.
_PHASE_KEYS = {"ice": "i", "drizzle": "d", "unsure": "q"}

#: Labels that must not be fed to a classifier as ground truth. ``"unsure"``
#: says the reviewer could not decide; ``"mixed"`` says the image holds more
#: than one particle, so a single label is the wrong shape for it. Both are
#: worth *recording* -- a mixed-image rate is a measurement -- and neither is a
#: training target. Consumers filter on this rather than each re-deciding.
TRAINING_EXCLUDED = frozenset({"unsure", "mixed"})

#: Where a verdict came from. The plan's symptom, verbatim: *the 149-177 MB
#: bulk sidecars beside 57-300-byte human ones*. Human review, a cluster's bulk
#: label and a model's prediction were written into one namespace with nothing
#: to tell them apart, so every accuracy number computed from a sidecar was
#: really computed against a mixture of human judgement and the very clustering
#: it was meant to evaluate.
VALID_SOURCES = frozenset({"human", "bulk-cluster", "model"})

#: A verdict written before provenance existed. It is NOT one of
#: :data:`VALID_SOURCES`: a legacy record is *unattributed*, and writing
#: ``"human"`` onto it would invent the one fact this schema exists to carry.
#: Old sidecars are read and round-tripped unchanged; only new writes are
#: required to say where they came from.
LEGACY_SOURCE = None


def _load_queue_file(path: Path) -> dict[str, list[dict]]:
    """A named, ordered particle list for a curated review pass -- the answer to
    "I don't know where to provide labels" for a specific set (a labeled-data
    re-review, a clustering candidate list, anything narrower than "every particle
    in a flight"). Shape: ``{"queue_name": [{"flight": ..., "particle_index": ...,
    "note": ...}, ...]}``. ``note`` is optional, shown alongside the particle as
    context for why it's in the queue.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for name, items in data.items():
        # An underscore-prefixed key is reserved metadata, not a queue --
        # `review_sampling.COVERAGE_KEY` writes a sample's coverage statement
        # there, in the same file as the particle list, so a labelled set can
        # say what it covers. Skipped by the rule rather than by naming that one
        # key, so a later metadata block does not have to edit this loop.
        if name.startswith("_"):
            continue
        for item in items:
            if "flight" not in item or ("particle_index" not in item
                                        and "second" not in item):
                raise ValueError(
                    f"queue {name!r}: every item needs 'flight' and 'particle_index' "
                    f"(or 'second', for a per-second queue), got {item!r}")
    _queue_purposes(data)  # a malformed purpose block refuses the file at startup
    return data


#: The labels a per-second queue offers when its file carries no ``_choices`` list
#:
SECOND_CHOICES = ("liquid", "mixed", "ice", "can't tell")


def _schima_habit_letters() -> tuple[str, ...]:
    """The habit letters the v3.5 Schima et al. (2024) tree can write, read from its code.

    Parsed from :func:`arrayprobe_uiops.habit._holroyd_new_impl` (the port of
    ``holroyd_new.m``): every string literal passed to its ``result(...)``, in the
    order the tree first returns it. Read, never typed, so the vocabulary follows the
    engine; ``tests/test_triage_habit_vocabulary.py`` checks it against the vendored
    ``holroyd_new.m`` as a second source.
    """
    import ast
    import inspect
    import textwrap

    from arrayprobe_uiops import habit as _habit_v35

    tree = ast.parse(textwrap.dedent(inspect.getsource(_habit_v35._holroyd_new_impl)))
    pos: dict[str, tuple[int, int]] = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "result" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            at = (node.lineno, node.col_offset)
            c = node.args[0].value
            pos[c] = min(pos.get(c, at), at)
    # Ordered by first appearance in the source, so the list reads as the tree does.
    letters = tuple(sorted(pos, key=pos.__getitem__))
    if not letters:
        raise RuntimeError("no habit letters found in arrayprobe_uiops.habit._holroyd_new_impl")
    return letters


#: The IMPACTS habit classes (Schima et al. 2024) a reviewer may give a particle, as the
#: letters the v3.5 engine's ``holroyd_new`` writes; stored as a verdict's optional
#: ``habit`` field. Read from the engine on first use (:func:`_schima_habit_letters`),
#: so ``import arrayprobe.cli`` loads no v3.5 module; ``HABIT_CHOICES`` resolves through
#: the module ``__getattr__`` below.
_HABIT_CHOICES: tuple[str, ...] | None = None


def _habit_choices() -> tuple[str, ...]:
    """The Schima habit letters, read from the v3.5 engine once and cached."""
    global _HABIT_CHOICES
    if _HABIT_CHOICES is None:
        _HABIT_CHOICES = _schima_habit_letters()
    return _HABIT_CHOICES


def __getattr__(name: str):
    """``HABIT_CHOICES`` on first access (PEP 562), keeping the v3.5 import lazy."""
    if name == "HABIT_CHOICES":
        return _habit_choices()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


#: Each habit letter in words, copied from the ``holroyd_habit`` variable's own
#: ``Description`` attribute in UIOPS v3.5's ``imgProc_sm.m:588-590`` (the ``iNewHabit == 1``
#: branch, the Schima et al. 2024 scheme); ``tests/test_triage_habit_vocabulary.py`` re-reads
#: those lines and compares. A letter absent here is shown as the letter alone.
HABIT_WORDS = {"M": "zero image", "C": "center-out image", "t": "tiny", "o": "bad/split",
               "l": "linear", "a": "aggregate", "g": "graupel", "s": "sphere",
               "h": "hexagonal", "i": "irregular", "d": "dendrite"}
#: The most particles a per-second page draws (the README's "up to 30").
SECOND_GALLERY_MAX = 30


def is_second_item(item: dict) -> bool:
    """Whether a queue item is keyed by (flight, second) rather than by particle."""
    return "second" in item and "particle_index" not in item


def _second_choices(data: dict) -> tuple[str, ...]:
    """The per-second labels a loaded queue file offers: its ``_choices``, else the default."""
    got = data.get("_choices")
    if isinstance(got, list) and got and all(isinstance(c, str) for c in got):
        return tuple(got)
    return SECOND_CHOICES


def _resolve_second_flight(name, flights: dict) -> str | None:
    """A per-second item's flight as a discovered key. ``"0215"`` (MMDD) matches the one
    discovered ``baseYYMMDD...`` flight with that date; anything else goes through
    :func:`_resolve_queue_flight`. ``None`` when nothing or more than one flight matches."""
    name = str(name)
    if re.fullmatch(r"\d{4}", name):
        hits = [k for k in flights if re.match(rf"base\d{{2}}{name}", k)]
        return hits[0] if len(hits) == 1 else None
    return _resolve_queue_flight(name, flights)


def _second_verdicts_path(decoded_dir: Path, flight: str) -> Path:
    """Per-second verdicts live in their own directory, never in a particle sidecar."""
    d = decoded_dir / "triage_second_verdicts"
    d.mkdir(exist_ok=True)
    return d / f"{flight}.json"


def _load_second_verdicts(decoded_dir: Path, flight: str) -> dict:
    """One flight's per-second verdicts (``{second: record}``), ``{}`` if none; fails closed
    with :class:`VerdictStoreError` on a present but unreadable file, as particle verdicts do."""
    p = _second_verdicts_path(decoded_dir, flight)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise VerdictStoreError(
            f"{p} exists but could not be read ({type(e).__name__}: {e}). "
            "Refusing to treat it as empty. Move or repair the file, then retry.") from e
    if not isinstance(data, dict):
        raise VerdictStoreError(f"{p} parsed as {type(data).__name__}, not an object of "
                                "second -> verdict. Refusing to overwrite it.")
    return data


def _save_second_verdict(decoded_dir: Path, flight: str, second: int, verdict: str, *,
                         queue: str | None = None, reviewer: str | None = None) -> dict:
    """Record one per-second label: read-modify-write under the verdict lock, written to a
    temporary file and moved into place, so a failed write never truncates the store.

    ``reviewer`` is required: a ``None`` or empty id raises ``ValueError`` before the
    store is read or written. Records already on disk without one still load."""
    reviewer = _clean_label(reviewer, "reviewer")
    if not reviewer:
        raise ValueError(REVIEWER_REQUIRED)
    with _verdict_lock:
        data = _load_second_verdicts(decoded_dir, flight)
        rec = {"verdict": verdict, "at": datetime.now(UTC).isoformat()}
        if queue:
            rec["queue"] = queue
        if reviewer:
            rec["reviewer"] = reviewer
        data[str(int(second))] = _with_history(data.get(str(int(second))), rec)
        p = _second_verdicts_path(decoded_dir, flight)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)
        return data


def _second_particles(proc_path: Path, second: int, limit: int = SECOND_GALLERY_MAX
                      ) -> tuple[list[int], int]:
    """``(indices, n_in_second)``: the accepted particles (reject code 0) of diameter_minR
    >= 0.1 mm in one second of day, read from the proc file's ``Time`` as stored, largest
    first, at most ``limit``. Reads only; computes no product value."""
    with _NC_LOCK, netCDF4.Dataset(proc_path) as ds:
        if "Time" not in ds.variables:  # nothing to place a particle in a second by
            return [], 0
        insec = _particle_seconds(ds.variables["Time"][:])
        hit = np.flatnonzero(np.floor(insec) == int(second))
        if hit.size == 0:
            return [], 0
        rc = (np.ma.filled(np.ma.asarray(ds.variables["image_auto_reject"][hit]), -1)
              if "image_auto_reject" in ds.variables else np.full(hit.size, ord("0")))
        diam = (np.ma.filled(np.ma.asarray(ds.variables["image_diam_minR"][hit],
                                           dtype=float), np.nan)
                if "image_diam_minR" in ds.variables else np.full(hit.size, np.inf))
    keep = is_accepted_code(np.asarray(rc).reshape(-1))
    keep &= np.asarray(diam).reshape(-1) >= 0.1
    sel = hit[keep]
    order = np.argsort(-np.asarray(diam).reshape(-1)[keep], kind="stable")
    return [int(i) for i in sel[order][:limit]], int(sel.size)


PURPOSE_KEY = "_purpose"
"""Optional top-level queue-file key: queue name -> what that queue's labels decide.
Shown under the queue's title on ``/``, ``/queue``, its index and its item pages; a queue
without an entry shows nothing. Underscore-prefixed, so it is never read as a queue."""


def _queue_purposes(data: dict) -> dict[str, str]:
    """The ``_purpose`` block of a loaded queue file, or ``{}`` when it has none."""
    block = data.get(PURPOSE_KEY, {})
    if not isinstance(block, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in block.items()):
        raise ValueError(f"{PURPOSE_KEY!r} must map queue names to text, got {block!r}")
    return dict(block)


def _purpose_html(text: str | None) -> str:
    """A queue's purpose line, or nothing when the queue file gave it none."""
    return f"<p class='purpose'>{html.escape(text)}</p>" if text else ""


def _review_queues(data: dict) -> dict[str, list[dict]]:
    """The queues in a loaded queue file, without its underscore metadata.

    :func:`_load_queue_file` returns the metadata too, on purpose
    (``test_review_sampling`` requires ``_coverage`` to survive the reader);
    the pages must not list it. Until 2026-09-15 the server installed the file
    whole, and ``/queue`` iterated ``_about`` as a queue: ``TypeError: string
    indices must be integers`` on VA1's ``spotcheck.json``."""
    return {name: items for name, items in data.items() if not name.startswith("_")}


RECHECK_PREFIX = "recheck-"
"""A queue whose name starts with this re-shows particles a person has already labelled, to
measure label agreement (Track V phase 2, ``arrayprobe.review_agreement``). Its verdicts go to
``<flight>.recheck.json`` so the first label is never overwritten, and its pages show only the
re-check's own verdict, so the second label is blind to the first."""


def is_recheck_queue(queue: str | None) -> bool:
    """Whether ``queue`` is a blind re-check queue (its name starts with :data:`RECHECK_PREFIX`)."""
    return bool(queue) and str(queue).startswith(RECHECK_PREFIX)


def _verdicts_path(decoded_dir: Path, flight: str, *, recheck: bool = False) -> Path:
    d = decoded_dir / "triage_verdicts"
    d.mkdir(exist_ok=True)
    return d / (f"{flight}.recheck.json" if recheck else f"{flight}.json")


class VerdictStoreError(RuntimeError):
    """A verdict sidecar exists and could not be read.

    Raised rather than returning ``{}``, because every caller that saves does a
    read-modify-write: an empty read followed by a save replaces a whole
    flight's labels with one entry.  **That is the exact failure this tool was
    built to replace** -- the artifact-based
    predecessor "lost labels", and returning ``{}`` here reintroduced it behind
    a quieter door.

    An absent sidecar is not this error.  A flight with no labels yet reads as
    ``{}`` and always has; only a file that is present and unreadable raises.
    """


def _load_verdicts(decoded_dir: Path, flight: str, *, recheck: bool = False) -> dict:
    """Read one flight's verdict sidecar (or its re-check store).  ``{}`` if there is none.

    Fails closed: an unparseable or unreadable sidecar raises
    :class:`VerdictStoreError` instead of reading as "no labels", so a save can
    never overwrite labels it could not see.
    """
    p = _verdicts_path(decoded_dir, flight, recheck=recheck)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise VerdictStoreError(
            f"{p} exists but could not be read ({type(e).__name__}: {e}). "
            "Refusing to treat it as empty -- saving now would replace every "
            "verdict in it. Move or repair the file, then retry."
        ) from e
    if not isinstance(data, dict):
        raise VerdictStoreError(
            f"{p} parsed as {type(data).__name__}, not an object of "
            "particle_index -> verdict. Refusing to overwrite it."
        )
    return data


_verdict_lock = threading.Lock()


#: What a reviewer id or queue name may contain. Both arrive in a POST body, and
#: this module already says why that matters for `verdict`: such a field is
#: "free-form attacker-reachable text that gets written to the sidecar JSON and
#: later interpolated into an HTML class attribute / badge". Two new
#: client-supplied fields get the same treatment rather than an exception.
_LABEL_OK = re.compile(r"^[A-Za-z0-9 ._@-]{1,64}$")


def _clean_label(value, field: str):
    """A reviewer id or queue name, or ``None``. Refuses anything else.

    Refuses rather than silently truncating or stripping: a reviewer id that
    quietly became a different string would attribute a label to someone who
    never gave it, which is the one thing this schema exists to get right.
    """
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _LABEL_OK.match(value):
        raise ValueError(
            f"{field} must be 1-64 characters of letters, digits, space, or "
            f"'.', '_', '@', '-'; got {value!r}")
    return value


#: The environment variable :func:`main` and ``arrayprobe triage`` read when no
#: ``--reviewer`` is given. An environment variable the labeller sets is still
#: *them saying who they are*; the OS username is not, and is never consulted --
#: a wrong attribution is worse than a missing one, because it is believed.
REVIEWER_ENV = "ARRAYPROBE_REVIEWER"


def _recordable_queue(name: str) -> str | None:
    """The queue name to store with a label, or ``None`` if it cannot be stored.

    A queue name comes from a queue file, not from the vocabulary this module
    controls, so one may fall outside :data:`_LABEL_OK`. Refusing it the way
    :func:`_clean_label` refuses a reviewer id would turn every save in that
    queue into a 500 and stop the labelling pass; recording ``None`` loses the
    queue name only, and :func:`run` prints which names that applies to at
    startup so the loss is visible before any label is made.
    """
    return name if _LABEL_OK.match(name) else None


#: Longest free-text comment stored with a label. A comment is prose a reviewer
#: types when the verdict alone is too blunt -- "two touching drops, called it
#: real on the larger" -- so it is deliberately NOT held to :data:`_LABEL_OK`,
#: which governs identifiers. The cap exists only so one pasted essay cannot
#: bloat a verdict file that a labelling pass rewrites after every particle.
COMMENT_MAX_CHARS = 2000


def _clean_comment(value) -> str | None:
    """A reviewer's free-text comment, or ``None`` when there is nothing to store.

    Whitespace-only is nothing. Over-long is truncated rather than refused: a
    labelling pass is the author sitting down for an hour, and losing the label
    because the comment ran long would be the wrong trade.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"comment must be a string; got {type(value).__name__}")
    text = value.strip()
    if not text:
        return None
    return text[:COMMENT_MAX_CHARS]


def _check_phase(phase) -> None:
    """Refuse a phase outside :data:`VALID_PHASES`; ``None`` (no phase given) passes."""
    if phase is not None and phase not in VALID_PHASES:
        raise ValueError(f"phase {phase!r} is not one of {sorted(VALID_PHASES)}")


#: Why a save without a reviewer id is refused, as the HTTP 400 body and the
#: ``ValueError`` message. Records written before the requirement still load.
REVIEWER_REQUIRED = (
    "a reviewer id is required: start the server with --reviewer <id> (or set "
    "ARRAYPROBE_REVIEWER), or post a 'reviewer' field; nothing was saved")


def _check_habit(habit) -> None:
    """Refuse a habit outside :data:`HABIT_CHOICES`; ``None`` (no habit given) passes."""
    if habit is not None and habit not in _habit_choices():
        raise ValueError(f"habit {habit!r} is not one of {list(_habit_choices())}")


def _verdict_record(verdict: str, note: str, source: str,
                    reviewer: str | None = None, queue: str | None = None,
                    comment: str | None = None, phase: str | None = None,
                    habit: str | None = None) -> dict:
    """One stored verdict, with the provenance the plan asked for.

    ``source`` is required and validated here rather than at the HTTP edge, so
    that every path into the store -- the browser, the bulk cluster route, a
    script importing this module -- is held to it. A verdict whose origin is
    unknown cannot be filtered out of a training set later, and filtering it out
    later is the whole point.

    ``at`` is UTC and ISO-8601; ``tool`` is this package's version, so a label
    can be traced to the code that rendered the image behind it.

    ``reviewer`` is required for every new label: ``None`` or an empty id raises
    ``ValueError``. Records already stored without one still load, so no earlier verdict is lost.
    """
    if source not in VALID_SOURCES:
        raise ValueError(
            f"verdict source {source!r} is not one of {sorted(VALID_SOURCES)}; "
            "a verdict without a stated source is refused")
    # The verdict itself is held to the same vocabulary the HTTP route enforces, so a
    # script importing this module cannot store a label (e.g. "accept") that the
    # browser could never write and a training set would then have to guess about.
    if verdict not in VALID_VERDICTS:
        raise ValueError(
            f"verdict {verdict!r} is not one of {sorted(VALID_VERDICTS)}")
    reviewer = _clean_label(reviewer, "reviewer")
    if not reviewer:
        raise ValueError(REVIEWER_REQUIRED)
    queue = _clean_label(queue, "queue")
    record = {
        "verdict": verdict,
        "note": note,
        "source": source,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tool": __version__,
    }
    if reviewer:
        record["reviewer"] = reviewer
    if queue:
        record["queue"] = queue
    comment = _clean_comment(comment)
    if comment:
        record["comment"] = comment
    _check_phase(phase)
    if phase is not None:
        record["phase"] = phase
    _check_habit(habit)
    if habit is not None:
        record["habit"] = habit
    return record


def _with_history(previous, record: dict) -> dict:
    """``record`` with ``previous`` appended to its ``history``, oldest first.

    A label is never replaced, only superseded: the record it supersedes moves into
    ``history`` minus its own ``history`` (which is carried forward ahead of it). A
    legacy record moves in verbatim, with no field added or invented; a stored value
    that is not an object is kept as ``{"legacy_value": value}``. With no previous
    record ``record`` is returned unchanged, so a first label has no ``history`` key
    and keeps the shape every reader already knows. Top-level fields stay the current
    label, so no reader of the sidecar changes.
    """
    if previous is None:
        return record
    if isinstance(previous, dict):
        older = list(previous.get("history", []))
        older.append({k: v for k, v in previous.items() if k != "history"})
    else:
        older = [{"legacy_value": previous}]
    record["history"] = older
    return record


def _save_verdict(
    decoded_dir: Path, flight: str, particle_index: int, verdict: str, note: str = "",
    *, source: str, reviewer: str | None = None, queue: str | None = None,
    comment: str | None = None, phase: str | None = None, habit: str | None = None,
) -> dict:
    """Record one verdict. ``source`` is keyword-only and has no default.

    No default on purpose: a default would be a guess about who labelled this
    particle, written into the file as though it were known.

    ``comment`` is the reviewer's own free text for a particle the four verdicts
    describe badly. It is stored only when non-empty, so labels made without one
    keep exactly the shape they had before. ``None`` means *unchanged*: a comment
    already stored for this particle is carried into the new record, so
    re-clicking a verdict on a revisited particle cannot erase it (it did until
    2026-10-01). An empty or whitespace-only string means *clear*.

    ``phase`` (one of :data:`VALID_PHASES`) is stored when given. When it is not
    given, a phase already stored for this particle is carried into the new
    record, so changing a verdict never loses a phase label; a record that never
    had one keeps exactly the shape it had before.

    ``habit`` (one of :data:`HABIT_CHOICES`, the Schima et al. 2024 letters) follows
    the same rule as ``phase``: stored when given, carried forward when not, and a
    record that never had one keeps its shape.
    """
    recheck = is_recheck_queue(queue)
    p = _verdicts_path(decoded_dir, flight, recheck=recheck)
    record = _verdict_record(verdict, note, source, reviewer, queue, comment, phase, habit)
    with _verdict_lock:
        data = _load_verdicts(decoded_dir, flight, recheck=recheck)
        previous = data.get(str(particle_index))
        if phase is None and isinstance(previous, dict) and "phase" in previous:
            record["phase"] = previous["phase"]
        if habit is None and isinstance(previous, dict) and "habit" in previous:
            record["habit"] = previous["habit"]
        if comment is None and isinstance(previous, dict) and "comment" in previous:
            record["comment"] = previous["comment"]
        # A two-particle sub-label survives re-clicking "two particles", and only that.
        if verdict == "mixed" and isinstance(previous, dict):
            for key in ("two_real", "real_parts", "parts_gap"):
                if key in previous:
                    record[key] = previous[key]
        data[str(particle_index)] = _with_history(previous, record)
        p.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        return data


def parts_gap_of(record) -> int:
    """The piece gap a stored record's ``real_parts`` are numbered at.

    :func:`_save_parts` records it as ``parts_gap``; a record saved before that key existed
    was numbered with every separate piece its own number, so it reads as gap 0. A record
    with no ``real_parts`` points at no piece and takes the page's :data:`PIECE_GAP_DIODES`.
    """
    if isinstance(record, dict) and "real_parts" in record:
        return int(record.get("parts_gap", 0))
    return PIECE_GAP_DIODES


#: The piece gaps the particle page offers (``?gap=N``), in diodes.
GAP_CHOICES = (0, 2, 4, 8)
#: The widest ``?gap=`` a page accepts; anything else is ignored rather than raised.
_GAP_MAX = 64


def gap_override(qs: dict) -> int | None:
    """The ``?gap=N`` a particle page was asked for, or ``None`` (absent or not a whole
    number of diodes in 0..:data:`_GAP_MAX`), so the page falls back to :func:`parts_gap_of`."""
    raw = (qs or {}).get("gap", [None])[0]
    try:
        g = int(raw)
    except (TypeError, ValueError):
        return None
    return g if 0 <= g <= _GAP_MAX else None


#: How many slices per diode make a particle "tall" for the page layout: a particle longer
#: along the flight than this times its width across the array draws a figure taller than
#: wide, so the particle page moves the gap choice and the rest of the properties beside the
#: figure instead of under it. Display only.
TALL_ASPECT = 1.0


def is_tall_particle(info: dict) -> bool:
    """Whether the particle page lays out ``info``'s particle as tall: ``image_length``
    (slices) above :data:`TALL_ASPECT` times ``image_width`` (diodes). ``False`` when either
    is missing or not a number. Display only."""
    raw_length = info.get("image_length")
    raw_width = info.get("image_width")
    if raw_length is None or raw_width is None:
        return False
    try:
        length = float(raw_length)
        width = float(raw_width)
    except (TypeError, ValueError):
        return False
    return width > 0 and length > TALL_ASPECT * width


def gap_choice_html(path: str, qs: dict | None, current: int) -> str:
    """The "Pieces split at gap: 0 · 2 · 4 · 8" row: each a link back to this page with
    ``gap`` set and every other query parameter (the queue's ``order``) kept."""
    links = []
    for g in GAP_CHOICES:
        q = {k: v for k, v in (qs or {}).items() if k != "gap"}
        q["gap"] = [str(g)]
        href = html.escape(f"{path}?{urllib.parse.urlencode(q, doseq=True)}")
        sel = " sel" if g == current else ""
        cur = " aria-current='true'" if g == current else ""
        links.append(f"<a class='gapchoice{sel} pbtn' href='{href}'{cur}>{g}</a>")
    extra = ("" if current in GAP_CHOICES else
             f" <span class='muted'>(now {int(current)})</span>")
    return ("<div class='gap-row' id='gap-row'><span class='muted'>Pieces split at gap "
            f"(diodes):</span> {' '.join(links)}{extra}"
            "<div class='muted gap-help'>How far apart two patches of shadow must be, in empty "
            "diodes, to count as separate pieces. 0: any break makes a new piece. "
            f"{PIECE_GAP_DIODES} (the default): one fragmented crystal stays one piece. "
            "Why it is here: the stray-pixel correction splits an image into pieces by this "
            "same gap and keeps only the real particle, so your answers (one particle, or "
            "which numbered piece is real) are what the gap rule is scored and chosen "
            "against. Switch it when the drawn pieces do not match what you see; the "
            "choice only renumbers the pieces on this page, is stored with your answer, "
            "and changes no processed number.</div></div>")


def particle_meta_html(info: dict, extras: dict) -> str:
    """The reject code and the air temperature, side by side above the particle image."""
    temp = _property_value_html(extras.get("air_temperature"), "°C", "temp")
    return ("<div class='pmeta' id='pmeta'>"
            "<span class='pm pm-reject'><span class='pm-k'>Reject code</span> "
            f"{reject_code_html(info.get('reject_code'))}</span>"
            "<span class='pm pm-temp'><span class='pm-k'>Air temperature</span> "
            f"{temp}</span></div>"
            f"{record_line_html(extras.get('record'))}")


#: Shown for a record-line field the files do not carry. Never a guess.
# ---------------------------------------------------------------------------------------------
# Time navigation on the record strip (viewer-survey item 2, after xpms2d's time widget and
# SODA-2's per-period paging). A record is located by the time its particles carry as stored --
# the proc file's ``Time`` (HHMMSS) beside ``parent_rec_num`` -- and nothing else is computed.

_UTC_RE = re.compile(r"^\s*(\d{1,2}):?(\d{2})(?::?(\d{2}))?\s*$")


def parse_utc(text: str) -> int:
    """``hh:mm:ss`` (or ``hhmmss``, ``hh:mm``) as seconds of day; refuses anything else.

    The message names what was given and what is wanted, because it is shown on the page.
    """
    m = _UTC_RE.match(text or "")
    if m is None:
        raise ValueError(f"{text!r} is not a UTC time: give hh:mm:ss, e.g. 06:40:17")
    hh, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    if hh > 23 or mm > 59 or ss > 59:
        raise ValueError(f"{text!r} is not a UTC time: hours run 0-23, minutes and "
                         f"seconds 0-59")
    return hh * 3600 + mm * 60 + ss


def _utc_text(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _particle_seconds(hhmmss) -> np.ndarray:
    from arrayprobe_uiops.sizedist_core import _hhmmss_to_insec

    return _hhmmss_to_insec(np.ma.filled(np.ma.asarray(hhmmss, dtype=float), np.nan).reshape(-1))


def record_at_time(parent_rec_num, hhmmss, seconds: int) -> int:
    """The record of the first particle, in file order, stamped at or after ``seconds`` of day.

    ``parent_rec_num`` and ``hhmmss`` are the proc file's own columns; a particle with a
    non-finite time or record is skipped. Raises ``ValueError`` naming the file's time span when
    no particle is that late.
    """
    prn = np.ma.filled(np.ma.asarray(parent_rec_num, dtype=float), np.nan).reshape(-1)
    insec = _particle_seconds(hhmmss)
    ok = np.isfinite(insec) & np.isfinite(prn)
    if not ok.any():
        raise ValueError("this proc file carries no finite particle times")
    hit = np.flatnonzero(ok & (insec >= seconds))
    if hit.size == 0:
        span = insec[ok]
        raise ValueError(f"no particle at or after {_utc_text(seconds)} UTC: this file's "
                         f"particle times run {_utc_text(span.min())}-"
                         f"{_utc_text(span.max())} UTC")
    return int(prn[hit[0]])


def record_seconds(parent_rec_num, hhmmss, rec: int) -> int:
    """Seconds of day of the first particle in record ``rec`` or after, as stored."""
    prn = np.ma.filled(np.ma.asarray(parent_rec_num, dtype=float), np.nan).reshape(-1)
    insec = _particle_seconds(hhmmss)
    hit = np.flatnonzero(np.isfinite(insec) & np.isfinite(prn) & (prn >= rec))
    if hit.size == 0:
        raise ValueError(f"no particle with a time in record {rec} or after")
    return int(insec[hit[0]])


#: The steps the strip's time bar offers, in seconds.
STRIP_TIME_STEPS = (-60, -10, 10, 60)


def strip_time_nav_html(flight: str, rec: int, n: int, by: str, *,
                        t: str = "", message: str = "") -> str:
    """The go-to-time form and the step links, carrying ``n`` and ``by`` along.

    A plain GET form, so Enter in the box submits it and nothing else on the page changes.
    """
    esc = html.escape(flight)
    q = f"n={n}&amp;by={html.escape(by)}"
    links = [f"<a href='/strip/{esc}?rec={max(1, rec - 1)}&amp;{q}'>&minus;1 record</a>",
             f"<a href='/strip/{esc}?rec={rec + 1}&amp;{q}'>+1 record</a>"]
    links += [f"<a href='/strip/{esc}?rec={rec}&amp;dt={s}&amp;{q}'>"
              f"{'&minus;' if s < 0 else '+'}{abs(s)} s</a>" for s in STRIP_TIME_STEPS]
    note = (f"<p class='muted' id='strip-time-msg'>{html.escape(message)}</p>"
            if message else "")
    return (f"<form id='strip-time' method='get' action='/strip/{esc}'>"
            f"<label>go to UTC <input name='t' size='8' placeholder='hh:mm:ss' "
            f"value='{html.escape(t)}'></label>"
            f"<input type='hidden' name='n' value='{n}'>"
            f"<input type='hidden' name='by' value='{html.escape(by)}'>"
            f" <button type='submit'>go</button> &middot; {' &middot; '.join(links)}"
            f"</form>{note}")


NO_VALUE = "—"


def _tas_csv_of(proc_path) -> Path | None:
    """The decode's ``<stem>.tas.csv`` beside ``proc.<stem>.<channel>.nc``, or ``None``."""
    name = Path(proc_path).name
    if not (name.startswith("proc.") and name.endswith(".nc")):
        return None
    stem = name[len("proc."):-len(".nc")].rsplit(".", 1)[0]
    return Path(proc_path).parent / f"{stem}.tas.csv"


_TAS_ROWS: dict = {}


def _tas_rows(tas_csv: Path):
    """``(timehhmmss, tas)`` from the sidecar, cached by path and mtime; ``None`` if unreadable."""
    stamp = _mtime_ns(tas_csv)
    if stamp is None:
        return None
    key = str(tas_csv)
    hit = _TAS_ROWS.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    try:
        from .readers.tasinfo import load_tas_info

        rows = load_tas_info(tas_csv)
    except Exception:                          # noqa: BLE001 -- a viewer shows "—"
        rows = None
    _TAS_ROWS.clear()                          # one flight's sidecar at a time
    _TAS_ROWS[key] = (stamp, rows)
    return rows


def _stored_number(ds, name: str, idx: int) -> float | None:
    """The stored value of ``name`` at ``idx``; ``None`` when absent, masked or not finite."""
    if name not in ds.variables:
        return None
    value = ds.variables[name][idx]
    if np.ma.is_masked(value):
        return None
    x = float(value)
    return x if np.isfinite(x) else None


def _record_context(proc_ds, idx: int, tas_csv: Path | None) -> dict:
    """The record-level values the files already carry for particle ``idx`` (the first item
    of the visualisation-tool survey, after xpms2d's per-record text line). Every value is
    read as stored -- the proc file's ``parent_rec_num``, ``particle_num``, ``Time``, ``msec``,
    ``DMT_DOF_SPEC_OVERLOAD`` and ``inter_arrival``, and the first ``.tas.csv`` row at the
    record's second. Nothing is computed; a value the files lack is ``None`` and renders as
    :data:`NO_VALUE`."""
    # Stored numbers, unit strings and explanatory text share one dict by design; without the
    # annotation mypy infers ``float | None`` from the first keys and rejects the text values.
    rec: dict[str, object] = {name: _stored_number(proc_ds, name, idx)
           for name in ("parent_rec_num", "particle_num", "Time", "msec",
                        "DMT_DOF_SPEC_OVERLOAD", "inter_arrival")}
    overload = proc_ds.variables.get("DMT_DOF_SPEC_OVERLOAD")
    rec["overload_units"] = getattr(overload, "Units", None) if overload is not None else None
    rec["tas"] = rec["tas_rows"] = None
    rec["tas_why"] = "no .tas.csv beside the proc file"
    rows = _tas_rows(tas_csv) if tas_csv is not None else None
    if rows is not None and rec["Time"] is not None:
        hhmmss, tas = rows
        at = np.flatnonzero(np.floor(np.asarray(hhmmss, dtype=float)) == rec["Time"])
        if at.size:
            rec["tas"], rec["tas_rows"] = float(tas[at[0]]), int(at.size)
        else:
            assert tas_csv is not None             # rows is only set from _tas_rows(tas_csv)
            rec["tas_why"] = f"no {tas_csv.name} row at this second"
    elif rows is not None:
        rec["tas_why"] = "the proc file carries no record Time"
    return rec


def record_line_html(rec: dict | None) -> str:
    """One compact line of the record's state, below the reject code and temperature."""
    rec = rec or {}

    def field(key: str, label: str, text: str, title: str = "") -> str:
        tip = f" title='{html.escape(title, quote=True)}'" if title else ""
        return (f"<span class='pr pr-{key}'{tip}><span class='pm-k'>{label}</span> "
                f"{html.escape(text)}</span>")

    def num(key: str):
        return rec.get(key)

    if num("parent_rec_num") is None:
        record = NO_VALUE
    else:
        record = f"#{int(num('parent_rec_num'))}"
        if num("particle_num") is not None:
            record += f", particle {int(num('particle_num'))}"
    if num("Time") is None:
        when = NO_VALUE
    else:
        t = int(num("Time"))
        when = f"{t // 10000:02d}:{t // 100 % 100:02d}:{t % 100:02d}"
        if num("msec") is not None:
            when += f".{int(num('msec')):03d}"
        when += " UTC"
    tas = NO_VALUE if num("tas") is None else f"{num('tas'):.1f} m/s"
    tas_tip = (f"first of {rec['tas_rows']} .tas.csv row(s) at the record's second"
               if num("tas") is not None else rec.get("tas_why") or "")
    over = NO_VALUE if num("DMT_DOF_SPEC_OVERLOAD") is None else _sig3(
        num("DMT_DOF_SPEC_OVERLOAD"))
    over_tip = ("DMT_DOF_SPEC_OVERLOAD as stored: a flag for SPEC/DMT probes, dead time for "
                "PMS probes" + (f"; Units '{rec['overload_units']}'"
                                if rec.get("overload_units") else ""))
    gap = NO_VALUE if num("inter_arrival") is None else f"{_sig3(num('inter_arrival'))} s"
    return ("<div class='prec' id='prec'>"
            + field("rec", "Record", record)
            + field("time", "Record time", when)
            + field("tas", "TAS", tas, tas_tip)
            + field("over", "Overload / dead time", over, over_tip)
            + field("ia", "Inter-arrival", gap, "inter_arrival as stored")
            + "</div>")


def _save_parts(decoded_dir: Path, flight: str, particle_index: int, two_real,
                real_parts, *, queue: str | None = None,
                gap: int = PIECE_GAP_DIODES) -> dict:
    """Add the two-particle sub-label to a particle labelled "two particles".

    ``two_real`` is how many of the particles are real (0, 1 or 2). ``real_parts`` is the list
    of the real pieces' numbers (:func:`triage_context.particle_parts`, 1-based, in order along
    the flight), or ``None`` when the image has no separate pieces to point at. ``gap`` is the
    piece gap the page numbered them at, stored beside them as ``parts_gap`` so the numbers
    keep pointing at the same pieces whatever :data:`PIECE_GAP_DIODES` becomes. Raises
    ``LookupError`` when the particle has no "two particles" verdict to attach it to, and
    ``ValueError`` on a value outside those shapes. Nothing else in the record changes.
    """
    if two_real not in (0, 1, 2) or isinstance(two_real, bool):
        raise ValueError(f"two_real {two_real!r} is not 0, 1 or 2")
    if not isinstance(gap, int) or isinstance(gap, bool) or gap < 0:
        raise ValueError(f"parts_gap {gap!r} is not a non-negative number of diodes")
    if real_parts is not None:
        if (not isinstance(real_parts, list)
                or not all(isinstance(k, int) and not isinstance(k, bool) and k >= 1
                           for k in real_parts)
                or len(set(real_parts)) != len(real_parts)):
            raise ValueError(f"real_parts {real_parts!r} is not a list of distinct piece numbers")
        if two_real == 0 and real_parts:
            raise ValueError("no piece can be real when none of the particles is")
        if real_parts and len(real_parts) != two_real:
            raise ValueError(f"{len(real_parts)} piece(s) named for {two_real} real particle(s)")
    recheck = is_recheck_queue(queue)
    p = _verdicts_path(decoded_dir, flight, recheck=recheck)
    with _verdict_lock:
        data = _load_verdicts(decoded_dir, flight, recheck=recheck)
        record = data.get(str(particle_index))
        if not isinstance(record, dict) or record.get("verdict") != "mixed":
            raise LookupError(f"particle {particle_index} has no 'two particles' verdict yet")
        record = data[str(particle_index)] = _with_history(record, dict(record))
        record["two_real"] = two_real
        if real_parts is None:
            record.pop("real_parts", None)
            record.pop("parts_gap", None)
        else:
            record["real_parts"] = sorted(real_parts)
            record["parts_gap"] = gap
        p.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        return data


def _save_phase(decoded_dir: Path, flight: str, particle_index: int, phase: str,
                *, queue: str | None = None) -> dict:
    """Set the phase of a particle that already has a verdict, changing nothing else.

    Every other field of the stored record -- verdict, comment, source, reviewer,
    queue, time -- is kept as it is, so a phase chosen after the verdict cannot
    cost the comment typed with it. A particle with no verdict yet raises
    :class:`LookupError` and nothing is written: a phase alone is not a record,
    and the page holds it until a verdict is chosen, then saves both together.
    """
    if phase is None:
        raise ValueError("a phase is required")
    _check_phase(phase)
    recheck = is_recheck_queue(queue)
    p = _verdicts_path(decoded_dir, flight, recheck=recheck)
    with _verdict_lock:
        data = _load_verdicts(decoded_dir, flight, recheck=recheck)
        record = data.get(str(particle_index))
        if not isinstance(record, dict):
            raise LookupError(f"particle {particle_index} of {flight} has no verdict yet; "
                              "choose one and the phase is saved with it")
        record = data[str(particle_index)] = _with_history(record, dict(record))
        record["phase"] = phase
        p.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        return data


def _save_comment(decoded_dir: Path, flight: str, particle_index: int, comment: str,
                  *, queue: str | None = None) -> dict:
    """Set or clear the comment of a particle that already has a verdict, changing nothing else.

    The mirror of :func:`_save_phase`. The comment is cleaned as on the verdict path
    (trimmed, capped); an empty or whitespace-only string removes the stored comment.
    Every other field -- verdict, phase, source, reviewer, queue, time -- is kept as it
    is. A particle with no verdict yet raises :class:`LookupError` and nothing is
    written: a comment alone is not a record, and the page holds it until a verdict is
    chosen, then saves both together.
    """
    if comment is None:
        raise ValueError("a comment is required; an empty string clears the stored one")
    text = _clean_comment(comment)
    recheck = is_recheck_queue(queue)
    p = _verdicts_path(decoded_dir, flight, recheck=recheck)
    with _verdict_lock:
        data = _load_verdicts(decoded_dir, flight, recheck=recheck)
        record = data.get(str(particle_index))
        if not isinstance(record, dict):
            raise LookupError(f"particle {particle_index} of {flight} has no verdict yet; "
                              "choose one and the comment is saved with it")
        record = data[str(particle_index)] = _with_history(record, dict(record))
        if text:
            record["comment"] = text
        else:
            record.pop("comment", None)
        p.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        return data


def _saved_time(at) -> str | None:
    """``HH:MM:SS`` from a stored record's ISO-8601 ``at``, or ``None`` when it is not one.

    Only digits and colons come back, so the result is safe in page text and in a script.
    """
    m = re.match(r"\d{4}-\d\d-\d\dT(\d\d:\d\d:\d\d)", at) if isinstance(at, str) else None
    return m.group(1) if m else None


def _save_verdicts_bulk(
    decoded_dir: Path, flight: str, particle_indices, verdict: str, note: str = "",
    *, source: str = "bulk-cluster", reviewer: str | None = None,
    queue: str | None = None, habit: str | None = None,
) -> dict:
    """One read-modify-write for many indices at once -- a cluster's bulk
    label can cover thousands of particles, and _save_verdict's per-call
    read-modify-write would make that O(n) full-file rewrites instead of 1.

    ``source`` defaults to ``"bulk-cluster"`` here and nowhere else: bulk is
    what this function *is*, and the default states a fact rather than guessing
    one. A caller doing something else passes its own.
    """
    p = _verdicts_path(decoded_dir, flight)
    record = _verdict_record(verdict, note, source, reviewer, queue, habit=habit)
    with _verdict_lock:
        data = _load_verdicts(decoded_dir, flight)
        for idx in particle_indices:
            key = str(int(idx))
            data[key] = _with_history(data.get(key), dict(record))
        p.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        return data


def _index_path(decoded_dir: Path, flight: str) -> Path:
    d = decoded_dir / "triage_index"
    d.mkdir(exist_ok=True)
    return d / f"{flight}.npz"


def _build_flight_index(proc_path: Path) -> dict:
    """``reject_code``/``diam_minR`` for every particle, plus the proc file's
    own ``mtime``/size as the staleness stamp -- read once, from the proc
    file this index was built from."""
    with _NC_LOCK, netCDF4.Dataset(proc_path) as ds:
        rc = np.asarray(ds.variables["image_auto_reject"][:]).astype(np.int32)
        diam = np.asarray(ds.variables["image_diam_minR"][:], dtype=np.float64)
    st = proc_path.stat()
    return {"proc_mtime": st.st_mtime, "proc_size": st.st_size,
            "reject_code": rc, "diam_minR": diam}


class _BoundedCache:
    """A small least-recently-used map whose values are built at most once per key at a time.

    The triage server's memory incident (2026-10-01: 44 GB on a 17.8-million-particle flight)
    had three per-request whole-array costs. This is the one mechanism that removes them: a value
    is built under a per-key lock, so N concurrent first requests build once and the other N-1
    wait for that build, and at most ``maxsize`` values are held, the least recently used
    evicted first. ``valid`` lets a caller reject a held value (the index's sidecar was deleted
    or rewritten) so it is rebuilt rather than served.
    """

    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self._data: OrderedDict = OrderedDict()
        self._guard = threading.Lock()
        self._key_locks: dict = {}

    def __len__(self) -> int:
        with self._guard:
            return len(self._data)

    def keys(self) -> list:
        with self._guard:
            return list(self._data)

    def clear(self) -> None:
        with self._guard:
            self._data.clear()

    def _hit(self, key, valid):
        if key in self._data:
            value = self._data[key]
            if valid is None or valid(value):
                self._data.move_to_end(key)
                return True, value
            del self._data[key]
        return False, None

    def get_or_build(self, key, build, valid=None):
        with self._guard:
            hit, value = self._hit(key, valid)
            if hit:
                return value
            lock = self._key_locks.setdefault(key, threading.Lock())
        with lock:
            try:
                with self._guard:
                    hit, value = self._hit(key, valid)
                    if hit:
                        return value
                value = build()
                with self._guard:
                    self._data[key] = value
                    self._data.move_to_end(key)
                    while len(self._data) > self.maxsize:
                        self._data.popitem(last=False)
                return value
            finally:
                with self._guard:
                    if self._key_locks.get(key) is lock:
                        del self._key_locks[key]


#: Each flight's index, held once in memory: at most two flights (the 17.8M-particle flight's
#: compact index is ~90 MB), keyed by the proc file's path, size and ``st_mtime_ns`` and the
#: sidecar's path.
_INDEX_CACHE = _BoundedCache(maxsize=2)

#: ``_selected_particles``' results (one int32 index array per flight and group, ~71 MB at
#: 17.8M particles), so paging through a group does not re-run ``argsort`` over the population.
_SELECTION_CACHE = _BoundedCache(maxsize=3)

#: The diode page's whole-file derived results (inter-arrival histogram, particles per second):
#: a few kB each, keyed by the proc file's path, size and ``st_mtime_ns``.
_PANEL_CACHE = _BoundedCache(maxsize=8)


def _stat_stamp(path: Path):
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _file_key(path) -> tuple:
    st = Path(path).stat()
    return (str(path), st.st_size, st.st_mtime_ns)


def _compact_index(index: dict) -> dict:
    """The index with the narrowest dtypes that hold every value exactly, read-only.

    ``reject_code`` becomes ``int8`` when every code fits (they are character codes); otherwise
    it stays as read. ``diam_minR`` becomes ``float32`` only when the round trip is exact (the
    proc file stores it as ``float32``); :func:`_selected_particles` widens it back to
    ``float64`` before sorting, so the sort sees the dtype and values it always saw.
    """
    rc = np.asarray(index["reject_code"])
    if rc.size == 0 or (int(rc.min()) >= -128 and int(rc.max()) <= 127):
        rc = rc.astype(np.int8)
    diam = np.asarray(index["diam_minR"], dtype=np.float64)
    narrow = diam.astype(np.float32)
    if np.array_equal(narrow.astype(np.float64), diam, equal_nan=True):
        diam = narrow
    rc.setflags(write=False)
    diam.setflags(write=False)
    return {"proc_mtime": index["proc_mtime"], "proc_size": index["proc_size"],
            "reject_code": rc, "diam_minR": diam}


def _flight_index(decoded_dir: Path, flight: str, proc_path: Path) -> dict:
    """The cached per-particle index for ``flight``, built once and reused.

    ``_render_flight`` used to open the proc netCDF and run
    ``np.where``/``np.argsort`` over the whole particle population on *every*
    request -- the cost the 2026-09-10 large-flight measurement
    found to be 4.8 s on a
    12.4M-particle
    real flight. This sidecar makes that a one-time cost per flight (or per
    proc-file change) rather than a per-request one.

    **Staleness** is the proc file's own ``mtime`` and size, stored inside the
    cache and compared against the file on disk -- the simplest signal that
    does not require touching the proc file's own contents (no `.call`-style
    stamp exists for a *read-only viewer's* cache of someone else's output,
    unlike the processing stages' own `.call` sidecars, which stamp a file
    they themselves wrote). A proc file reprocessed with the same name and a
    newer mtime invalidates the cache automatically; one regenerated with an
    identical mtime and size (vanishingly unlikely, and no worse than not
    having a cache at all) would not, which is the same class of edge case
    every mtime-based cache in existence accepts.

    **Format: an uncompressed ``.npz``** (2026-09-29, Track V phase 1's open
    item). The first version wrote JSON lists; on the 12.4M-particle flight the
    index was 150.8 MB and ``json.load`` alone cost ~3.1 s of every cached page
    (Phase 1 of the modernisation). The contract is unchanged:
    a dict of two arrays plus the staleness stamp. The file is written to a
    per-thread temporary name and moved into place, so two threads building the
    same index cannot interleave their writes; an older ``.json`` index is
    simply ignored and rebuilt as ``.npz``.


    **Held in memory once** (2026-10-01 memory incident): the sidecar used to be
    ``np.load``-ed on every ``/flight`` and ``/sheet`` request (~214 MB at 17.8M particles), and
    concurrent first requests each built their own copy. :data:`_INDEX_CACHE` now holds at most
    two flights' compact indexes (:func:`_compact_index`), built once under a per-key lock. A held
    index is served only while the sidecar on disk carries the stamp it had when the index was
    held, so deleting or rewriting the sidecar still forces a reload or rebuild.
    """
    return _flight_index_entry(decoded_dir, flight, proc_path)[1]["index"]


def _flight_index_entry(decoded_dir: Path, flight: str, proc_path: Path) -> tuple:
    """``(token, entry)`` for :func:`_flight_index`: ``entry["index"]`` is the held index, and
    ``token`` names that exact copy (proc file key plus the sidecar stamp it was held with)."""
    proc_path = Path(proc_path)
    path = _index_path(decoded_dir, flight)
    st = proc_path.stat()
    key = (str(proc_path), st.st_size, st.st_mtime_ns, str(path))
    entry = _INDEX_CACHE.get_or_build(
        key, lambda: _load_or_build_index(path, proc_path),
        valid=lambda e: _stat_stamp(path) == e["sidecar"])
    return key + (entry["sidecar"],), entry


def _load_or_build_index(path: Path, proc_path: Path) -> dict:
    """:func:`_flight_index`'s disk half: the ``.npz`` sidecar if current, else a build that
    writes it. Returns ``{"index": <compact index>, "sidecar": <its stamp after this call>}``."""
    st = proc_path.stat()
    if path.exists():
        try:
            with np.load(path, allow_pickle=False) as z:
                if (float(z["proc_mtime"]) == st.st_mtime
                        and int(z["proc_size"]) == st.st_size):
                    index = {"proc_mtime": st.st_mtime, "proc_size": st.st_size,
                             "reject_code": z["reject_code"], "diam_minR": z["diam_minR"]}
                    return {"index": _compact_index(index), "sidecar": _stat_stamp(path)}
        except (OSError, ValueError, KeyError):
            pass  # a corrupt or foreign cache rebuilds rather than blocking the page
    built = _build_flight_index(proc_path)
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp, "wb") as fh:
        np.savez(fh, proc_mtime=np.float64(built["proc_mtime"]),
                 proc_size=np.int64(built["proc_size"]),
                 reject_code=np.asarray(built["reject_code"], dtype=np.int32),
                 diam_minR=np.asarray(built["diam_minR"], dtype=np.float64))
    try:
        os.replace(tmp, path)
    except PermissionError:
        # Windows: another thread has the index open. This request's arrays are
        # correct; the next request writes the cache.
        tmp.unlink(missing_ok=True)
    return {"index": _compact_index(built), "sidecar": _stat_stamp(path)}


def _selected_particles(decoded_dir: Path, flight: str, proc_path: Path,
                         group: str) -> np.ndarray:
    """Particle indices for ``group`` ("accepted"/"rejected"/"all"), largest
    diameter first -- the selection ``_render_flight`` and ``_render_sheet``
    both need, from the cached index rather than a fresh netCDF read.

    The result depends only on the index and ``group``, so it is held in
    :data:`_SELECTION_CACHE` (read-only, ``int32`` when the population allows) and paging
    re-runs no whole-population ``where``/``argsort``. The sort is the one it always was:
    ``np.argsort`` (default kind) over ``float64`` diameters, so ties keep their order.
    """
    token, entry = _flight_index_entry(decoded_dir, flight, proc_path)
    idx = entry["index"]
    g = group if group in ("accepted", "rejected") else "all"

    def select() -> np.ndarray:
        rc = np.asarray(idx["reject_code"])
        diam = np.asarray(idx["diam_minR"], dtype=np.float64)
        if g == "accepted":
            idx_all = np.where(is_accepted_code(rc))[0]
        elif g == "rejected":
            idx_all = np.where(~is_accepted_code(rc))[0]
        else:
            idx_all = np.arange(len(rc))
        order = np.argsort(diam[idx_all])[::-1]  # largest first -- the interesting ones
        out = idx_all[order]
        if out.size < 2**31 - 1:
            out = out.astype(np.int32)
        out.setflags(write=False)
        return out

    # Keyed on the held index's token (proc file stamp and sidecar stamp): a reloaded or
    # rebuilt index carries a new token, so a selection made from a stale one is never served.
    return _SELECTION_CACHE.get_or_build((token, g), select)


STYLE = """<style>
  /* The hidden attribute wins over every display rule below: `.actions` sets display:flex,
     which otherwise shows the two-particle row before "Two particles" is chosen, where a
     count cannot be saved (the server answers 409) and the 0/1/2 keys are ignored. */
  [hidden] { display:none !important; }
  /* The two theme blocks are the only place a colour is written down; every rule below
     takes its colours from these tokens, so both themes follow. */
  :root { --bg:#f7f8f9; --surface:#fff; --surface-2:#eef1f3; --ink:#1d2329; --muted:#5c6672;
    --line:#d9dee3; --accent:#1e6f68; --accent-bg:#e9f2f1; --bad:#b4402f; --bad-bg:#f9edeb;
    --amber:#8a6415; --amber-bg:#fdf3d8; --img-bg:#fff; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#131719; --surface:#1b2125; --surface-2:#22292e; --ink:#e6eaed; --muted:#99a3ad;
      --line:#333c43; --accent:#48b2a5; --accent-bg:#1c2e2c; --bad:#e2685a; --bad-bg:#33231f;
      --amber:#e0b768; --amber-bg:#3a2f14; --img-bg:#fff; }
  }
  /* One set of spacing, radius, font and size tokens for both themes. System fonts only:
     the tool runs offline, so nothing is fetched. --img-bg stays white in the dark theme
     because the particle PNGs are drawn on white. */
  :root { color-scheme:light dark;
    --space-1:.25rem; --space-2:.5rem; --space-3:1rem; --space-4:2rem; --radius:8px;
    --font-ui:"Segoe UI",system-ui,-apple-system,sans-serif;
    --font-data:ui-monospace,Consolas,"Cascadia Mono",monospace;
    --text-s:.82rem; --text-m:.95rem; --text-l:1.4rem; }
  * { box-sizing: border-box; }
  /* The page column. Until a page wraps its content in <main>, the body is the column. */
  body { background:var(--bg); color:var(--ink); font-family:var(--font-ui);
    font-size:var(--text-m); line-height:1.5; max-width:1180px; margin:0 auto;
    padding:var(--space-4) 1.75rem 4rem; -webkit-font-smoothing:antialiased; }
  main { max-width:1180px; margin:0 auto; }
  /* With a <main>, the body spans the window so the header bar can, and <main> is the column;
     the header's side padding lines its text up with the column's. */
  body:has(> main) { max-width:none; padding:0 0 4rem; }
  body:has(> main) > main { padding:var(--space-4) 1.75rem 0; }
  header { background:var(--surface); border-bottom:1px solid var(--line);
    padding:var(--space-3) max(1.75rem, calc((100% - 1180px) / 2 + 1.75rem)); }
  header h1 { margin:0; }
  header p { margin:var(--space-1) 0 0; color:var(--muted); font-size:var(--text-s);
    max-width:46rem; }
  header .brand { margin:0; font-size:1.05rem; font-weight:650; }
  header h1.brand { font-size:var(--text-l); }
  header .brand a { color:var(--ink); text-decoration:none; }
  footer { margin-top:var(--space-4); padding-top:var(--space-3); border-top:1px solid var(--line);
    color:var(--muted); font-size:var(--text-s); }
  /* A footer beside <main> lines its text up with the column, as the header does. */
  body:has(> main) > footer {
    padding:var(--space-3) max(1.75rem, calc((100% - 1180px) / 2 + 1.75rem)) 0; }
  .purpose { margin:var(--space-1) 0 var(--space-2); max-width:46rem; }
  td .purpose { margin:var(--space-1) 0 0; font-size:var(--text-s); }
  .card { background:var(--surface); border:1px solid var(--line); border-radius:var(--radius);
    padding:var(--space-3); }
  a { color:var(--accent); text-underline-offset:0.18em; }
  a:hover { text-decoration-thickness:2px; }
  h1 { font-size:var(--text-l); line-height:1.25; letter-spacing:-0.01em;
    margin:0 0 var(--space-1); }
  h2 { font-size:1.1rem; line-height:1.3; margin:var(--space-4) 0 var(--space-2); }
  code { font-family:var(--font-data); font-size:0.9em; background:var(--surface-2);
    padding:0.05em 0.35em; border-radius:4px; }
  summary { cursor:pointer; }
  .muted { color:var(--muted); font-size:var(--text-s); }
  table.flights { border-collapse:separate; border-spacing:0; width:100%; margin-top:var(--space-3);
    font-size:var(--text-s); font-variant-numeric:tabular-nums; background:var(--surface);
    border:1px solid var(--line); border-radius:var(--radius); overflow:hidden; }
  table.flights th, table.flights td { text-align:left; padding:var(--space-2) 0.8rem;
    border-bottom:1px solid var(--line); }
  table.flights th { font-size:0.7rem; text-transform:uppercase; letter-spacing:0.04em;
    color:var(--muted); font-weight:600; }
  table.flights tbody tr:nth-child(even) { background:var(--surface-2); }
  table.flights tbody tr:hover { background:var(--accent-bg); }
  table.flights tbody tr:last-child td { border-bottom:0; }
  .toolbar { display:flex; gap:0.8rem; align-items:center; margin:var(--space-3) 0; flex-wrap:wrap;
    font-size:var(--text-s); }
  .toolbar a.tab { padding:0.35rem 0.8rem; border-radius:999px; border:1px solid var(--line);
    text-decoration:none; color:var(--ink); background:var(--surface); }
  .toolbar a.tab:hover { border-color:var(--accent); }
  .toolbar a.tab.active { background:var(--accent); border-color:var(--accent);
    color:var(--surface); }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:0.8rem;
    margin-top:var(--space-3); }
  .pcard { background:var(--surface); border:1px solid var(--line);
    border-left:3px solid var(--line);
    border-radius:0 var(--radius) var(--radius) 0; padding:0.4rem; font-size:0.68rem;
      color:var(--muted); position:relative; }
  .pcard:hover { border-color:var(--muted); }
  .pcard.v-artifact { border-left-color:var(--bad); }
  .pcard.v-real { border-left-color:var(--accent); }
  .pcard.v-unsure { border-left-color:var(--amber); }
  .pcard.v-mixed { border-left-color:var(--muted); }
  .pcard img { width:100%; height:110px; object-fit:contain; background:var(--img-bg);
    border-radius:3px; image-rendering:pixelated; }
  .pcard a { text-decoration:none; color:inherit; display:block; }
  .badge { position:absolute; top:0.3rem; right:0.3rem; font-size:0.6rem; font-weight:700;
    padding:0.05rem 0.35rem; border-radius:999px; background:var(--ink); color:var(--surface); }
  .pager { display:flex; gap:0.6rem; margin-top:1.2rem; font-size:var(--text-s); }
  /* Image left, controls right, so the image and every button fit one screen.
     The image column is as wide as its content, up to 640px; the right column
     takes the rest. The properties from the size-distribution note down sit under the image
     in the left column (.detail-more, author 2026-10-02), so the page is shorter. Below
     900px everything stacks: image, controls, the rest. */
  .detail { display:grid; grid-template-columns:fit-content(640px) minmax(18rem, 1fr);
    grid-template-areas:"fig side" "more side"; grid-template-rows:auto 1fr;
    gap:1.5rem; align-items:flex-start; margin-top:var(--space-3); }
  .detail > .pimg { grid-area:fig; }
  .detail-side { grid-area:side; min-width:0; }
  .detail-more { grid-area:more; min-width:0; }
  .detail-side .actions:first-child { margin-top:0; }
  /* A tall particle (is_tall_particle: more slices along the flight than diodes across)
     draws a figure far taller than wide. The figure then spans both rows and everything that
     sat under it -- the gap choice (moved into .detail-side by the page) and .detail-more --
     goes up the right-hand column beside it, so the page is no taller than the figure.
     Desktop width only; below 900px everything stacks as before. */
  @media (min-width: 901px) {
    .detail.tall { grid-template-areas:"fig side" "fig more"; }
  }
  .detail-side .gap-row { margin-top:var(--space-3); }
  @media (max-width: 900px) {
    .detail { grid-template-columns:minmax(0, 1fr); grid-template-areas:"fig" "side" "more";
      grid-template-rows:auto; }
  }
  /* Never stretched: width and height both auto, so the browser keeps the PNG's own aspect
     (drawn at one diode = one slice by particle_figure), and align-items:flex-start stops the
     grid row from stretching the image to the height of the column beside it. */
  /* width:fit-content + justify-self:start: the figure is as wide as the image, not as wide as
     the grid column (which .detail-more below can widen to 640px), so the text inside wraps to
     the image. */
  .pimg { margin:0; min-width:0; width:fit-content; justify-self:start;
    max-width:min(100%, 640px); }
  .detail img, .pimg img { display:block; width:auto; height:auto; max-width:100%; max-height:75vh;
    object-fit:contain; background:var(--img-bg); border:1px solid var(--line);
    border-radius:var(--radius); }
  .pimg figcaption { font-size:0.72rem; color:var(--muted); margin-top:0.35rem; max-width:30rem;
    line-height:1.4; }
  /* The image sets the figure's width; the text above it (properties) and below it (gap choice,
     caption) wraps to that width instead of widening the column, so the figure stays compact
     and the controls beside or under it stay in one frame. contain:inline-size
     makes each text block contribute no width of its own; the 16rem floor keeps a very narrow
     particle's text readable. Display only. */
  .pimg > :not(img) { contain:inline-size; min-width:16rem; overflow-wrap:anywhere; }
  .kv { font-family:var(--font-data); font-size:var(--text-s); line-height:1.7;
    font-variant-numeric:tabular-nums; }
  .kv b { color:var(--muted); font-weight:600; display:inline-block; min-width:11em;
    font-family:var(--font-ui); }
  .kv small.var { font-weight:400; font-size:0.78em; opacity:0.8; margin:0 0.6em 0 0.3em; }
  .actions { display:flex; flex-wrap:wrap; gap:0.6rem; margin-top:var(--space-3); }
  kbd { font-family:var(--font-data); font-size:0.75em;
        border:1px solid currentColor; border-radius:3px; padding:0 0.28em;
        opacity:0.75; margin-left:0.35em; }
  .keyhint { margin-top:var(--space-2); font-size:var(--text-s); }
  .keyhint kbd { margin-left:0; }
  .qh { font-size:1.1rem; margin:1.4rem 0 0.2rem; }
  .qcode { font-family:var(--font-data); font-size:0.72rem; color:var(--muted); }
  table.queues td { padding:0.35rem 0.8rem; }
  table.queues td.qn { font-family:var(--font-data); font-size:var(--text-s); color:var(--muted);
    text-align:right; white-space:nowrap; }
  td.qbar { width:45%; }
  .qsum { margin:0.3rem 0 0.7rem; }
  .sbar { display:flex; height:0.6rem; border-radius:999px; overflow:hidden;
    background:var(--line); min-width:8rem; max-width:34rem; }
  .sbar span { display:block; height:100%; }
  .sbar .s-real { background:var(--accent); }
  .sbar .s-artifact { background:var(--bad); }
  .sbar .s-mixed { background:var(--muted); }
  .sbar .s-unsure { background:var(--amber); }
  .sbar .s-other { background:var(--ink); }
  .sbar .s-left { background:var(--line); }
  .qsum-text { font-size:0.8rem; color:var(--muted); margin-top:0.25rem; }
  tr.q-done td.qn { color:var(--accent); font-weight:700; }
  .comment { margin-top:0.8rem; max-width:34rem; }
  .comment label { display:block; font-size:0.8rem; margin-bottom:0.25rem; }
  .comment textarea { width:100%; font:inherit; font-size:0.85rem; padding:0.45rem 0.6rem;
    border:1px solid var(--line); border-radius:6px; background:var(--surface);
    color:var(--ink); resize:vertical; }
  .comment-row { display:flex; flex-wrap:wrap; gap:0.6rem; align-items:center;
    margin-top:0.35rem; font-size:0.8rem; }
  .comment-row button { font:inherit; padding:0.35rem 0.8rem; cursor:pointer; color:var(--ink);
    border:1px solid var(--line); border-radius:6px; background:var(--surface); }
  .comment-status { color:var(--muted); }
  .comment-status.unsaved { color:var(--amber); font-weight:700; }
  button { transition:background-color .12s, border-color .12s, color .12s; }
  button.verdict { font:inherit; font-size:0.85rem; font-weight:700; padding:0.6rem 1.1rem;
    border-radius:var(--radius); border:2px solid var(--line); background:var(--surface-2);
      color:var(--muted); cursor:pointer; }
  button.verdict:hover, button.phase:hover, .comment-row button:hover {
    border-color:var(--muted); color:var(--ink); }
  button.verdict.v-artifact.sel { background:var(--bad-bg); color:var(--bad);
    border-color:var(--bad); }
  button.verdict.v-real.sel { background:var(--accent-bg); color:var(--accent);
    border-color:var(--accent); }
  button.verdict.v-unsure.sel { background:var(--amber-bg); color:var(--amber);
    border-color:var(--amber); }
  button.phase { font:inherit; font-size:0.8rem; padding:0.4rem 0.9rem; cursor:pointer;
                 border:1px solid var(--line); border-radius:6px; background:var(--surface);
                 color:var(--ink); }
  /* One focus ring for every control reached by keyboard. */
  input:focus-visible, select:focus-visible, summary:focus-visible,
  button:focus-visible, a:focus-visible, textarea:focus-visible {
    outline:2px solid var(--accent); outline-offset:2px; }
  button.phase.sel { background:var(--accent-bg); color:var(--accent); border-color:var(--accent); }
  button.verdict.v-mixed.sel { background:var(--surface-2); color:var(--ink);
    border-color:var(--muted); }
  /* Every control on the particle page (verdict, phase, two-particle count, piece number,
     gap choice, comment save, prev/next): one size, one shape, one selected state. */
  button.pbtn, a.pbtn { font:inherit; font-size:0.85rem; font-weight:700;
    min-width:3rem; height:2.4rem; padding:0 0.9rem; box-sizing:border-box;
    display:inline-flex; align-items:center; justify-content:center; gap:0.3rem;
    border-radius:var(--radius); border:2px solid var(--line); background:var(--surface);
    color:var(--ink); cursor:pointer; text-decoration:none; vertical-align:middle; }
  button.pbtn:hover, a.pbtn:hover { border-color:var(--muted); }
  button.pbtn.sel, a.pbtn.sel { background:var(--accent-bg); color:var(--accent);
    border-color:var(--accent); }
  button.verdict.v-artifact.sel.pbtn { background:var(--bad-bg); color:var(--bad);
    border-color:var(--bad); }
  button.verdict.v-unsure.sel.pbtn { background:var(--amber-bg); color:var(--amber);
    border-color:var(--amber); }
  .gap-row { display:flex; flex-wrap:wrap; gap:0.4rem; align-items:center;
    margin:0.4rem 0; font-size:0.8rem; }
  .pnav { display:flex; flex-wrap:wrap; gap:0.4rem; align-items:center; }
  .pmeta { display:flex; flex-wrap:wrap; gap:0.5rem 1.2rem; align-items:baseline;
    margin:0 0 0.5rem; font-size:1.05rem; font-weight:700; }
  .pmeta .pm-k { font-size:0.75rem; font-weight:400; color:var(--muted);
    text-transform:uppercase; letter-spacing:0.04em; margin-right:0.3rem; }
  .prec { display:flex; flex-wrap:wrap; gap:0.2rem 1rem; align-items:baseline;
    margin:-0.2rem 0 0.5rem; font-size:0.85rem; font-variant-numeric:tabular-nums; }
  .cnn { margin-top:var(--space-3); padding:0.7rem var(--space-3); background:var(--surface-2);
    border-radius:var(--radius); font-size:0.85rem; }
  .status { margin-top:0.7rem; font-size:var(--text-s); color:var(--muted); min-height:1.2em; }
  .cgrid { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr));
    gap:var(--space-3); margin-top:var(--space-3); }
  .ccard { background:var(--surface); border:1px solid var(--line); border-radius:var(--radius);
    padding:0.8rem; }
  .ccard img { width:100%; height:130px; object-fit:contain; background:var(--img-bg);
    border-radius:4px; image-rendering:pixelated; }
  .ccard .n { font-weight:700; font-size:1.05rem; margin:0.5rem 0 0.1rem; }
  .ccard .stats { font-family:var(--font-data); font-size:0.72rem; color:var(--muted);
    line-height:1.5; margin:0.4rem 0; }
  .ccard .actions { display:flex; gap:0.4rem; margin-top:0.5rem; }
  .ccard button.bulk { flex:1; font:inherit; font-size:0.75rem; font-weight:700;
    padding:0.4rem 0.3rem;
    border-radius:6px; border:1px solid var(--line); background:var(--surface-2);
      color:var(--muted); cursor:pointer; }
  .ccard button.bulk.v-artifact:hover { background:var(--bad-bg); color:var(--bad);
    border-color:var(--bad); }
  .ccard button.bulk.v-real:hover { background:var(--accent-bg); color:var(--accent);
    border-color:var(--accent); }
  .ccard .cstatus { font-size:0.72rem; color:var(--muted); min-height:1.1em; margin-top:0.3rem; }
</style>"""


#: What every particle page says under the image, so the reviewer knows what shape they see.
TRUE_ASPECT_NOTE = (
    "Drawn at true aspect: one diode across the array and one slice along the flight are the "
    "same size on screen, and the axes are in micrometres; the window size never stretches it. "
    "Top: the particle close up. Below, when the record is wider than the particle: the whole "
    "array, with the close-up boxed, so contact with an array edge stays visible. A slice is one "
    "diode wide only when the probe's clock tracked the airspeed."
)


def _content_box(c, margin: int = 2):
    """``(r0, r1, c0, c1)``: the rows and columns holding set pixels, plus ``margin``."""
    rows = np.flatnonzero(c.any(axis=1))
    cols = np.flatnonzero(c.any(axis=0))
    if rows.size == 0:
        return 0, c.shape[0], 0, c.shape[1]
    return (max(0, int(rows[0]) - margin), min(c.shape[0], int(rows[-1]) + 1 + margin),
            max(0, int(cols[0]) - margin), min(c.shape[1], int(cols[-1]) + 1 + margin))


def particle_figure(c, diode_um: float, figure_cls, parts=None):
    """The particle silhouette ``c`` (``(n_slices, n_diodes)``) as a figure at true aspect.

    One diode and one slice are the same length on screen (``aspect="equal"``) in every panel,
    the axes carry micrometres, and each panel is sized from the pixels it shows, never from a
    fixed box: an ``aspect="auto"`` image inside a minimum figure size stretched small particles,
    and that changed the shape a reviewer labels (author, 2026-10-01). When ``c`` is wider or
    taller than the particle, a close-up comes first and the whole frame second, with the
    close-up boxed. ``figure_cls`` is matplotlib's ``Figure``, passed in so this module keeps
    matplotlib a lazy import.
    """
    if c.size == 0:  # nothing set after cropping: draw one blank pixel, labelled as such
        c = np.zeros((1, 1), dtype=bool)
    n_slices, n_diodes = c.shape
    r0, r1, c0, c1 = _content_box(c)
    zoom = c[r0:r1, c0:c1]
    context = zoom.shape != c.shape
    z_in = min(0.3, 3.2 / max(zoom.shape))          # inches per pixel, close-up
    s_in = min(5.0 / n_diodes, 3.0 / n_slices)      # inches per pixel, whole frame
    z_h, z_w = zoom.shape[0] * z_in, zoom.shape[1] * z_in
    s_h, s_w = n_slices * s_in, n_diodes * s_in
    # Enough dots that every pixel survives in both panels; nearest-neighbour keeps edges.
    dpi = max(110, int(np.ceil(2.0 / min(z_in, s_in if context else z_in))))
    width = max(z_w, s_w if context else 0.0) + 1.4
    height = z_h + (s_h + 0.9 if context else 0.0) + 1.1
    fig = figure_cls(figsize=(width, height), dpi=dpi, layout="constrained")
    um = diode_um
    if context:
        gs = fig.add_gridspec(2, 1, height_ratios=[max(z_h, 0.3), max(s_h, 0.3)])
        ax, ax_s = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
    else:
        ax, ax_s = fig.add_subplot(111), None
    ax.imshow(zoom, cmap="Greys", aspect="equal", interpolation="nearest",
              extent=(c0 * um, c1 * um, r1 * um, r0 * um))
    ax.set_xlabel(f"across the array (µm; diode {um:g} µm)", fontsize=7)
    ax.set_ylabel("along the flight (µm)", fontsize=7)
    ax.set_title(f"close-up: {zoom.shape[1]} diodes × {zoom.shape[0]} slices", fontsize=7)
    ax.tick_params(labelsize=6)
    # Two or more separate pieces: each numbered at its centre, in order along the flight, so
    # a "two particles" label can say which one is real.
    if parts and len(parts) > 1:
        for part in parts:
            ax.text((part["col"] + 0.5) * um, (part["row"] + 0.5) * um, str(part["n"]),
                    color="#d62728", fontsize=9, fontweight="bold", ha="center", va="center",
                    bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "#d62728",
                          "lw": 0.6, "alpha": 0.85})
    if ax_s is not None:
        from matplotlib.patches import Rectangle

        ax_s.imshow(c, cmap="Greys", aspect="equal", interpolation="nearest",
                    extent=(0, n_diodes * um, n_slices * um, 0))
        ax_s.add_patch(Rectangle((c0 * um, r0 * um), (c1 - c0) * um, (r1 - r0) * um,
                                 fill=False, edgecolor="#d62728", linewidth=0.8))
        ax_s.set_title(f"whole record: {n_diodes} diodes × {n_slices} slices; "
                       "the box is the close-up", fontsize=7)
        ax_s.set_xlabel("across the array (µm)", fontsize=7)
        ax_s.tick_params(labelsize=6)
    return fig


def render_occupancy_svg(occupancy, flagged=(), *, width: int = 900,
                         height: int = 220) -> str:
    """A bar per diode, as inline SVG, with flagged diodes marked.

    SVG rather than matplotlib on purpose: the server serialises every pyplot
    render behind a lock because pyplot is not thread-safe, and a bar chart of
    128 numbers has no business on that lock. It also means the page carries no
    image request of its own.

    Bars are scaled to the largest occupancy rather than to 1.0. A stuck diode
    is obvious either way, but a flight whose highest occupancy is 0.04 would
    otherwise render as an empty box -- and "nothing to see" and "nothing
    measured" must not look the same.
    """
    values = [float(v) for v in occupancy]
    if not values:
        return "<p class='muted'>no particles counted -- nothing to plot</p>"
    flagged = set(int(i) for i in flagged)
    # The REPORTED peak and the DIVISOR are two different things. An all-zero
    # flight -- a decode with no shadowed slice anywhere -- has a real peak of
    # 0.0, and substituting 1.0 for it to avoid dividing by zero would both
    # print a peak that does not exist and, before this was split, raise on
    # `values.index(1.0)`. Divide by the substitute; report the truth.
    peak = max(values)
    scale = peak or 1.0
    peak_at = values.index(peak) + 1
    bar_w = max(1.0, width / len(values))
    bars = []
    for i, value in enumerate(values):
        bar_h = (value / scale) * (height - 20)
        colour = "var(--bad)" if i in flagged else "var(--accent)"
        bars.append(
            f"<rect x='{i * bar_w:.2f}' y='{height - 20 - bar_h:.2f}' "
            f"width='{max(bar_w - 0.5, 0.5):.2f}' height='{bar_h:.2f}' "
            f"fill='{colour}'><title>diode {i + 1}: {value:.4f}"
            f"{' (flagged)' if i in flagged else ''}</title></rect>")
    axis = (f"<line x1='0' y1='{height - 20}' x2='{width}' y2='{height - 20}' "
            f"stroke='var(--line)'/>")
    return (f"<svg viewBox='0 0 {width} {height}' width='100%' height='{height}' "
            f"role='img' aria-label='per-diode occupancy'>{''.join(bars)}{axis}"
            f"</svg>"
            f"<p class='muted'>peak {peak:.4f} at diode "
            f"{peak_at}; bars scale to the peak, not to 1.0</p>")


def render_intarr_svg(counts, centres, fitted=None, thresholds=(), *,
                      width: int = 900, height: int = 240) -> str:
    """Inter-arrival histogram, the fitted double-Poisson over it, and the
    thresholds, as inline SVG on a log-x axis.

    ``centres`` are the bin centres of :data:`arrayprobe.intarr_analysis.HIST_BINS`,
    which is ``logspace(-7, 0, 35)`` -- so the x axis is log by construction,
    and drawing it linearly would compress six of the seven decades the fit
    actually works over into the last few pixels.

    ``fitted`` is :func:`arrayprobe.intarr.bimodal_model` evaluated on the same
    centres, or ``None`` when the fit failed. **A failed fit draws no curve and
    says so**, rather than drawing a flat line that a reader could mistake for
    a fit that found nothing.
    """
    import math

    counts = [float(c) for c in counts]
    centres = [float(c) for c in centres]
    if not counts or not centres or len(counts) != len(centres):
        return "<p class='muted'>no inter-arrival histogram to plot</p>"

    plot_h = height - 24
    peak = max(counts)
    scale = peak or 1.0
    log_lo, log_hi = math.log10(centres[0]), math.log10(centres[-1])
    span = (log_hi - log_lo) or 1.0

    def x_of(value: float) -> float:
        return (math.log10(value) - log_lo) / span * width

    bar_w = width / len(counts)
    bars = "".join(
        f"<rect x='{x_of(c) - bar_w / 2:.2f}' "
        f"y='{plot_h - (n / scale) * plot_h:.2f}' "
        f"width='{max(bar_w - 1, 0.5):.2f}' "
        f"height='{(n / scale) * plot_h:.2f}' fill='var(--surface-2)' "
        f"stroke='var(--line)'><title>{c:.3g} s: {n:,.0f}</title></rect>"
        for c, n in zip(centres, counts, strict=True))

    curve = ""
    if fitted is not None:
        points = " ".join(
            f"{x_of(c):.2f},{plot_h - (max(v, 0.0) / scale) * plot_h:.2f}"
            for c, v in zip(centres, [float(f) for f in fitted], strict=True))
        curve = (f"<polyline points='{points}' fill='none' "
                 f"stroke='var(--accent)' stroke-width='2'/>")

    marks = "".join(
        f"<line x1='{x_of(t):.2f}' y1='0' x2='{x_of(t):.2f}' y2='{plot_h}' "
        f"stroke='var(--bad)' stroke-dasharray='4 3'><title>{label}: "
        f"{t:.3g} s</title></line>"
        for label, t in thresholds
        if t and centres[0] <= t <= centres[-1])

    note = ("" if fitted is not None else
            "<p class='muted'><b>No curve drawn: the double-Poisson fit did not "
            "converge for this population.</b> `block_thresholds` falls back to "
            "DEFAULT_THRESHOLD when that happens, and the output file cannot "
            "tell you it did -- which is the reason this panel exists.</p>")
    axis = (f"<line x1='0' y1='{plot_h}' x2='{width}' y2='{plot_h}' "
            f"stroke='var(--line)'/>")
    return (f"<svg viewBox='0 0 {width} {height}' width='100%' height='{height}' "
            f"role='img' aria-label='inter-arrival histogram'>"
            f"{bars}{curve}{marks}{axis}</svg>"
            f"<p class='muted'>log x, {centres[0]:.3g}-{centres[-1]:.3g} s; "
            f"peak count {peak:,.0f}</p>{note}")


def render_rate_svg(seconds, counts, tas_seconds=None, tas=None, *,
                    width: int = 900, height: int = 220) -> str:
    """Particles per second over the flight, with TAS overlaid when it is known.

    Two series on one time axis and two independent vertical scales, which is
    the only way to see the thing worth seeing: whether the rate moves with the
    airspeed or against it. Each series is scaled to its own maximum and both
    maxima are printed, because a dual-axis plot whose scales are not stated is
    a way of implying a correlation rather than showing one.

    ``tas_seconds``/``tas`` may be ``None`` -- the sidecar is a separate file and
    is routinely absent -- and the panel then says the overlay is missing rather
    than quietly drawing one series and looking complete.
    """
    seconds = [float(x) for x in seconds]
    counts = [float(c) for c in counts]
    if not seconds or len(seconds) != len(counts):
        return "<p class='muted'>no per-second rate to plot</p>"

    t0, t1 = min(seconds), max(seconds)
    span = (t1 - t0) or 1.0
    plot_h = height - 24

    def x_of(t: float) -> float:
        return (t - t0) / span * width

    peak = max(counts) or 1.0
    rate_points = " ".join(
        f"{x_of(t):.2f},{plot_h - (c / peak) * plot_h:.2f}"
        for t, c in zip(seconds, counts, strict=True))
    series = (f"<polyline points='{rate_points}' fill='none' "
              f"stroke='var(--accent)' stroke-width='1.5'/>")

    overlay, note = "", ""
    if tas_seconds is not None and tas is not None and len(tas_seconds):
        tas_seconds = [float(x) for x in tas_seconds]
        tas = [float(v) for v in tas]
        tas_peak = max(tas) or 1.0
        inside = [(t, v) for t, v in zip(tas_seconds, tas, strict=True)
                  if t0 <= t <= t1]
        if inside:
            pts = " ".join(f"{x_of(t):.2f},{plot_h - (v / tas_peak) * plot_h:.2f}"
                           for t, v in inside)
            overlay = (f"<polyline points='{pts}' fill='none' "
                       f"stroke='var(--muted)' stroke-width='1' "
                       f"stroke-dasharray='3 2'/>")
            note = (f" TAS (dashed) peaks at {tas_peak:,.1f}; the two series have "
                    f"INDEPENDENT vertical scales, so read shape against shape, "
                    f"not height against height.")
    if not overlay:
        note = (" No TAS overlay: the `.tas.csv` sidecar for this flight is not "
                "on disk, so the airspeed half of this panel is missing rather "
                "than flat.")

    axis = (f"<line x1='0' y1='{plot_h}' x2='{width}' y2='{plot_h}' "
            f"stroke='var(--line)'/>")
    return (f"<svg viewBox='0 0 {width} {height}' width='100%' height='{height}' "
            f"role='img' aria-label='particles per second'>"
            f"{series}{overlay}{axis}</svg>"
            f"<p class='muted'>{len(seconds):,} second(s); rate peaks at "
            f"{peak:,.0f} particle(s)/s.{note}</p>")


PACKAGE_PURPOSE = (
    "Look at individual optical-array-probe images and record whether each is a real "
    "particle or an artefact, and its phase; labels are stored beside the data and never "
    "change a processed number.")
"""The landing page's one line on what this tool is for (shown under the package name)."""


def _footer_html(decoded_dir: Path | None = None) -> str:
    """Where labels go, on every page. Read at render time: ``run`` sets the directory."""
    if decoded_dir is None:
        decoded_dir = getattr(TriageServer, "decoded_dir", None)
    where = (f"<code>{html.escape(str(Path(decoded_dir) / 'triage_verdicts'))}</code>"
             if decoded_dir is not None else "<code>triage_verdicts/</code>")
    return (f"<footer>Verdicts save to {where} -- a local file, "
            f"never the port's own output.</footer>")


def _page(body: str, title: str = "Particle Triage", *, intro: bool = False,
          decoded_dir: Path | None = None) -> bytes:
    """Every page: a full-width header naming the tool (linking home), the page in <main>,
    and a footer saying where labels are stored. ``intro`` adds the one-line purpose and
    makes the name the page's heading (the landing page)."""
    brand_tag = "h1" if intro else "div"
    tagline = f"<p>{html.escape(PACKAGE_PURPOSE)}</p>" if intro else ""
    header = (f"<header><{brand_tag} class='brand'><a href='/'>arrayprobe &middot; "
              f"Particle Triage</a></{brand_tag}>{tagline}</header>")
    return (f"<!doctype html><title>{title}</title>{STYLE}<body>{header}"
            f"<main>{body}</main>{_footer_html(decoded_dir)}</body>").encode()


class TriageServer(BaseHTTPRequestHandler):
    """The whole HTTP surface: routing, rendering and verdict storage in one handler.

    **Read this before adding a route.** Two properties are load-bearing and both
    came from real failures rather than from design taste:

    * **Every flight name is validated against discovered flights before it
      reaches a path** -- see :meth:`_valid_flight`. Names arrive from URL
      segments and POST bodies, and ``Path``'s ``/`` neither sanitises ``..``
      nor refuses an absolute right-hand side.
    * **Rendering and netCDF reads are serialised**, because ``matplotlib.pyplot``
      and ``netCDF4``/HDF5 are both thread-unsafe. That is two separate crashes
      under real use, each diagnosed with a concurrent-load stress test rather
      than argued.

    Class attributes rather than instance state because
    ``BaseHTTPRequestHandler`` constructs a new handler per request; :func:`run`
    sets them once before the server starts.
    """

    decoded_dir: Path  # set by run()
    #: name -> list of {"flight": str, "particle_index": int, "note": str}, set by run()
    #: from --queue-file. Empty by default -- /queue routes 404 gracefully with no file.
    queues: dict[str, list[dict]] = {}
    #: queue name -> what its labels decide, from the queue file's optional ``_purpose``
    #: block, set by run(). A queue with no entry shows no purpose text.
    purposes: dict[str, str] = {}
    #: Who is labelling, set once by :func:`run` from ``--reviewer`` or
    #: :data:`REVIEWER_ENV`. ``None`` means nobody said, and a label then
    #: records no reviewer at all -- never a guess from the OS username. It is
    #: server state rather than a page field because the person at the browser
    #: is the person who started the server, and routing an identity through
    #: page JavaScript would let the page state decide who a label belongs to.
    reviewer: str | None = None
    #: Whether to index products whose provenance is unrecorded, set once by :func:`run` from
    #: ``--accept-unstamped``. Default False: a product nothing records the engine for is
    #: refused and named on the index rather than reviewed (see :func:`_discover_flights`).
    accept_unstamped: bool = False
    #: ARM merged aircraft files for the particle page's air temperature, set once by
    #: :func:`run` from ``--met-dir``; ``None`` means the page says how to get one.
    met: MetFolder | StateFile | None = None
    #: Folder whose ``_runs/`` the Run page lists at ``/runs``, set by :func:`run` from
    #: ``--run-root``. ``None`` until then: the first run launched from ``/run`` sets it to the
    #: output folder typed on the form, so its record is listed without a restart.
    run_root: Path | None = None
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003 -- quiet the default stderr spam
        """Silence the per-request stderr line.

        Overridden rather than left alone because this server is run in a
        terminal the user is also reading: the default one-line-per-request log
        buries the startup banner that tells them the URL, the decoded
        directory and which queues loaded.
        """

    def _flights(self) -> dict:
        return _discover_flights(self.decoded_dir, self.accept_unstamped)

    def _send(self, body: bytes, content_type: str = "text/html; charset=utf-8", status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _valid_flight(self, flight: str) -> bool:
        """Every route that takes a flight name -- GET or POST -- must check this
        before it ever reaches a filesystem path. `flight` arrives as untrusted
        input (a URL path segment, or a POST body field) and Path's `/` operator
        does not sanitize `..` or an absolute right-hand side; without this gate,
        `_verdicts_path` (decoded_dir / "triage_verdicts" / f"{flight}.json")
        would write wherever the caller says. Checking against the flights this
        server actually discovered on disk is a real whitelist, not a blocklist
        of bad characters."""
        return flight in self._flights()

    def do_GET(self):  # noqa: N802 -- required BaseHTTPRequestHandler name
        """Route a read request: the index, a flight, a particle, a rendered
        image, a cluster view, or a review queue.

        Routing is an explicit chain of path-segment matches rather than a
        table, so the flight-name validation above sits on the one path each
        route takes to the filesystem and cannot be skipped by a new entry.
        """
        parsed = urllib.parse.urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        qs = urllib.parse.parse_qs(parsed.query)
        order = qs.get("order", [QUEUE_ORDERS[0]])[0]
        if order not in QUEUE_ORDERS:
            order = QUEUE_ORDERS[0]

        try:
            if not parts:
                self._send(self._render_index())
            elif parts == ["run"]:
                from arrayprobe import run_page
                self._send(run_page.render_form().encode())
            elif parts[0] == "runs" and len(parts) <= 2:
                from arrayprobe import run_page
                run_root = self.run_root
                if len(parts) == 1:
                    self._send(run_page.render_runs(run_root).encode())
                else:
                    status, page = run_page.get_run_page(run_root, parts[1])
                    self._send(page.encode(), status=status)
            elif (parts[0] in ("flight", "particle", "clusters", "image", "thumb",
                                "sheet", "diodes", "strip")
                  and len(parts) >= 2):
                flight = parts[1]
                if not self._valid_flight(flight):
                    self._send(f"unknown flight {html.escape(str(flight))!r}".encode(),
                               status=404)
                    return
                if parts[0] == "diodes" and len(parts) == 2:
                    # Sampling is a query parameter because a dense flight holds
                    # tens of millions of images and a uniformity report
                    # converges long before all of them -- and because the
                    # sampling is part of the number, so it is shown.
                    stride = max(1, int(qs.get("stride", ["200"])[0]))
                    limit = int(qs.get("limit", ["5000"])[0])
                    self._send(self._render_diodes(flight, stride, limit))
                elif parts[0] == "strip" and len(parts) == 2:
                    rec = int(qs.get("rec", ["1"])[0])
                    n = max(1, min(int(qs.get("n", ["6"])[0]), 24))
                    by = qs.get("by", ["reject"])[0]
                    # Time navigation (viewer-survey item 2): ``t`` jumps to the first record
                    # at or after a UTC time, ``dt`` steps that many seconds from ``rec``.
                    # Malformed input is refused with the reason, before any file is opened.
                    t = qs.get("t", [""])[0].strip()
                    dt_text = qs.get("dt", [""])[0].strip()
                    try:
                        target = parse_utc(t) if t else None
                        dt = None
                        if dt_text:
                            if not re.fullmatch(r"[+-]?\d{1,5}", dt_text):
                                raise ValueError(f"{dt_text!r} is not a step in whole "
                                                 f"seconds, e.g. -10 or 60")
                            dt = int(dt_text)
                    except ValueError as exc:
                        esc = html.escape(flight)
                        self._send(_page(
                            f"<h1>Strip -- {esc}</h1>"
                            + strip_time_nav_html(flight, rec, n, by, t=t,
                                                  message=str(exc)),
                            title=f"Strip -- {flight}"), status=400)
                        return
                    self._send(self._render_strip(flight, rec, n, by, target=target,
                                                  dt=dt, t=t))
                elif parts[0] == "flight" and len(parts) == 2:
                    group = qs.get("group", ["accepted"])[0]
                    page = int(qs.get("page", ["1"])[0])
                    self._send(self._render_flight(flight, group, page,
                                                   want_pieces=pieces_filter(qs),
                                                   want_agreement=qs.get(
                                                       "agreement", ["0"])[0] == "1",
                                                   want_count=count_filter(qs)))
                elif parts[0] == "particle" and len(parts) == 3:
                    self._send(self._render_particle_page(flight, int(parts[2]), qs=qs))
                elif parts[0] == "clusters" and len(parts) == 2:
                    group = qs.get("group", ["accepted"])[0]
                    k = qs.get("k", [None])[0]
                    self._send(self._render_clusters(flight, group, int(k) if k else None))
                elif parts[0] == "image" and len(parts) == 3:
                    idx = int(parts[2].removesuffix(".png"))
                    crop = qs.get("crop", ["1"])[0] != "0"
                    gap = int(qs.get("gap", [str(PIECE_GAP_DIODES)])[0])
                    self._send(self._render_image(flight, idx, crop, gap), "image/png")
                elif parts[0] == "thumb" and len(parts) == 3:
                    idx = int(parts[2].removesuffix(".png"))
                    self._send(self._render_thumb(flight, idx), "image/png")
                elif parts[0] == "sheet" and len(parts) == 2:
                    group = qs.get("group", ["accepted"])[0]
                    page = int(qs.get("page", ["1"])[0])
                    self._send(self._render_sheet(flight, group, page))
                else:
                    self._send(b"not found", status=404)
            elif parts[0] == "queue":
                if len(parts) == 1:
                    self._send(self._render_queue_list())
                elif len(parts) == 2:
                    name = parts[1]
                    if name not in self.queues:
                        self._send(f"unknown queue {html.escape(name)!r}".encode(), status=404)
                        return
                    self._send(self._render_queue_index(name, order, pieces_filter(qs),
                                                        count_filter(qs)))
                elif len(parts) == 3:
                    name = parts[1]
                    if name not in self.queues:
                        self._send(f"unknown queue {html.escape(name)!r}".encode(), status=404)
                        return
                    pos = int(parts[2])
                    queue = self.queues[name]
                    if not (0 <= pos < len(queue)):
                        self._send(f"position {pos} out of range for queue "
                                   f"{html.escape(name)!r} (0-{len(queue) - 1})".encode(),
                                   status=404)
                        return
                    if is_second_item(queue[pos]):
                        self._send(self._render_queue_second(name, pos))
                    else:
                        self._send(self._render_queue_particle(name, pos, order, qs=qs))
                else:
                    self._send(b"not found", status=404)
            else:
                self._send(b"not found", status=404)
        except Exception as e:  # local dev tool: surface the error, don't crash the server
            self._send(f"<pre>{html.escape(f'{type(e).__name__}: {e}')}</pre>".encode(),
                       status=500)

    def _reviewer_for(self, body: dict) -> str | None:
        """Who to attribute this POST to: the body's claim, else the server's.

        A browser page posts no reviewer -- the buttons this module renders send
        ``{flight, particle_index, verdict}`` and, in a queue, ``queue`` -- so in
        the normal case this returns :attr:`reviewer`, the id the labeller gave
        at startup. A script POSTing its own ``reviewer`` is making a statement
        about a label it is writing on someone's behalf, and that statement
        wins. Neither path invents one: with no ``--reviewer`` and no body
        field this returns ``None`` and the stored record simply has no
        ``reviewer`` key, which :mod:`tools.export_human_verdicts` exports as
        ``null``.
        """
        return body.get("reviewer") or self.reviewer

    second_choices: tuple[str, ...] = SECOND_CHOICES

    def _render_queue_second(self, name: str, pos: int) -> bytes:
        """One per-second queue item: that second's particles as a grid of a few large,
        cropped panels per row, and the per-second labels. Blind by construction:
        it shows no classifier class, stratum or other computed call for the second."""
        queue = self.queues[name]
        item = queue[pos]
        second = int(item["second"])
        flight = _resolve_second_flight(item.get("flight"), self._flights())
        nav = (f"<p><a href='/queue/{urllib.parse.quote(name)}'>queue</a> &middot; "
               f"item {pos + 1} of {len(queue)}"
               + (f" &middot; <a href='/queue/{urllib.parse.quote(name)}/{pos - 1}'>prev</a>"
                  if pos > 0 else "")
               + (f" &middot; <a href='/queue/{urllib.parse.quote(name)}/{pos + 1}'>next</a>"
                  if pos + 1 < len(queue) else "") + "</p>")
        hms = f"{second // 3600:02d}:{second % 3600 // 60:02d}:{second % 60:02d} UTC"
        head = (f"<h1>{html.escape(name)} &mdash; second {second} ({hms})</h1>"
                + _purpose_html(self.purposes.get(name)) + nav)
        if item.get("note"):
            head += f"<p class=muted>{html.escape(str(item['note']))}</p>"
        if flight is None:
            return _page(head + f"<p>Flight {html.escape(str(item.get('flight')))!s} is not "
                         "in this decoded directory; launch with the directory that holds it."
                         "</p>", title=f"{name} {pos + 1}")
        try:
            saved = _load_second_verdicts(self.decoded_dir, flight).get(str(second))
        except VerdictStoreError as e:
            return _page(head + f"<p class=error>{html.escape(str(e))}</p>")
        idx, n = _second_particles(self._flights()[flight]["proc"], second)
        fq = urllib.parse.quote(flight)
        panels = "".join(
            f"<figure style='margin:0'><img src='/image/{fq}/{i}.png' "
            f"style='width:100%;image-rendering:pixelated' loading=lazy>"
            f"<figcaption style='font-size:1rem'>particle {i}</figcaption></figure>"
            for i in idx)
        grid = (f"<div style='display:grid;grid-template-columns:repeat(4,minmax(0,1fr));"
                f"gap:12px'>{panels}</div>" if idx else
                "<p>No accepted particle of 0.1 mm or more in this second.</p>")
        buttons = "".join(
            f"<button class=second-label data-v='{html.escape(c, quote=True)}' "
            f"onclick='label(this.dataset.v)'>{html.escape(c)}</button> "
            for c in self.second_choices)
        now = (f"<p>Saved: <b id=saved>{html.escape(saved['verdict'])}</b></p>" if saved
               else "<p>Saved: <b id=saved>not yet labelled</b></p>")
        body_js = json.dumps({"flight": flight, "second": second, "queue": name})
        nxt = f"/queue/{urllib.parse.quote(name)}/{pos + 1}" if pos + 1 < len(queue) else ""
        script = (f"<script>function label(v){{const b={body_js};b.verdict=v;"
                  "fetch('/second-verdict',{method:'POST',body:JSON.stringify(b)})"
                  ".then(r=>{if(!r.ok)throw r;document.getElementById('saved').textContent=v;"
                  f"if({json.dumps(nxt)})location.href={json.dumps(nxt)};}})"
                  ".catch(()=>alert('not saved'));}}</script>")
        return _page(head + f"<p>{len(idx)} of {n} accepted particles of 0.1 mm or more "
                     "in this second, largest first. Judge the second, not each particle."
                     f"</p>{grid}<p>{buttons}</p>{now}{script}",
                     title=f"{name} {pos + 1}")

    def do_POST(self):  # noqa: N802
        """Record a verdict, or a bulk verdict for a cluster.

        The only writing route. Verdicts go to a JSON sidecar under the decoded
        directory — never into a `proc` or `sd` file, because a label must not
        be able to change a computed number (that constraint is what keeps this
        tool inside the core package rather than in the enhancements).

        **Human and bulk labels are not interchangeable.** A 2026-08-27 bulk
        pass wrote 4.8 million cluster-derived verdicts over 14 human ones; the
        recovery's design lesson — provenance
        per verdict, separate namespaces — is the first item of the Track V
        modernisation plan.
        """
        try:
            parsed = urllib.parse.urlparse(self.path)
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            if parsed.path == "/run":
                from arrayprobe import run_page
                status, reply = run_page.handle_post(body, self.headers,
                                                     self.server.server_address[1])
                if reply.get("run_id") and TriageServer.run_root is None:
                    TriageServer.run_root = Path(str(body["out"])).resolve()
                self._send(json.dumps(reply).encode(), "application/json", status=status)
                return
            if parsed.path == "/state-file":
                self._post_state_file(body)
                return
            if parsed.path == "/second-verdict":
                flight = body.get("flight")
                if not self._valid_flight(flight):
                    self._send(f"unknown flight {html.escape(str(flight))!r}".encode(),
                               status=404)
                    return
                verdict = body.get("verdict")
                if verdict not in self.second_choices:
                    self._send(f"invalid label {verdict!r}, must be one of "
                               f"{list(self.second_choices)}".encode(), status=400)
                    return
                reviewer = self._reviewer_for(body)
                if not reviewer:
                    self._send(REVIEWER_REQUIRED.encode(), status=400)
                    return
                data = _save_second_verdict(self.decoded_dir, flight, int(body["second"]),
                                            verdict, queue=body.get("queue"),
                                            reviewer=reviewer)
                self._send(json.dumps({"ok": True, "count": len(data)}).encode(),
                           "application/json")
                return
            if parsed.path not in ("/verdict", "/verdict_bulk", "/phase", "/comment", "/parts"):
                self._send(b"not found", status=404)
                return
            flight = body.get("flight")
            if not self._valid_flight(flight):
                self._send(f"unknown flight {html.escape(str(flight))!r}".encode(), status=404)
                return
            phase = body.get("phase")
            if phase is not None and phase not in VALID_PHASES:
                self._send(f"invalid phase {phase!r}, must be one of "
                           f"{sorted(VALID_PHASES)}".encode(), status=400)
                return
            habit = body.get("habit")
            if habit is not None and habit not in _habit_choices():
                self._send(f"invalid habit {habit!r}, must be one of "
                           f"{list(_habit_choices())}".encode(), status=400)
                return
            if parsed.path == "/phase":
                # The phase of a particle already labelled; nothing else in its record
                # changes. Before any verdict there is no record to add it to: 409, and
                # the page keeps the phase and sends it with the verdict.
                if phase is None:
                    self._send(b"a phase is required", status=400)
                    return
                try:
                    data = _save_phase(self.decoded_dir, flight, int(body["particle_index"]),
                                       phase, queue=body.get("queue"))
                except LookupError as e:
                    self._send(str(e).encode(), status=409)
                    return
                self._send(json.dumps({"ok": True, "count": len(data)}).encode(),
                           "application/json")
                return
            if parsed.path == "/parts":
                try:
                    data = _save_parts(self.decoded_dir, flight, int(body["particle_index"]),
                                       body.get("two_real"), body.get("real_parts"),
                                       queue=body.get("queue"),
                                       gap=body.get("parts_gap", PIECE_GAP_DIODES))
                except LookupError as e:
                    self._send(str(e).encode(), status=409)
                    return
                except ValueError as e:
                    self._send(str(e).encode(), status=400)
                    return
                self._send(json.dumps({"ok": True, "count": len(data)}).encode(),
                           "application/json")
                return
            if parsed.path == "/comment":
                # The comment of a particle already labelled; nothing else in its record
                # changes, and "" clears it. Before any verdict there is no record: 409,
                # and the page holds the text and sends it with the verdict.
                comment = body.get("comment")
                if comment is None:
                    self._send(b"a comment is required; an empty string clears it",
                               status=400)
                    return
                try:
                    data = _save_comment(self.decoded_dir, flight, int(body["particle_index"]),
                                         comment, queue=body.get("queue"))
                except LookupError as e:
                    self._send(str(e).encode(), status=409)
                    return
                # No `at` in the reply: the record's own `at` is its verdict's time and
                # stays as it was, so the page says "Comment saved." without a time.
                self._send(json.dumps({"ok": True, "count": len(data)}).encode(),
                           "application/json")
                return
            verdict = body.get("verdict")
            if verdict not in VALID_VERDICTS:
                self._send(f"invalid verdict {verdict!r}, must be one of "
                           f"{sorted(VALID_VERDICTS)}".encode(), status=400)
                return
            if not self._reviewer_for(body):
                self._send(REVIEWER_REQUIRED.encode(), status=400)
                return
            note = body.get("note", "")
            if parsed.path == "/verdict":
                idx = int(body["particle_index"])
                # `source="human"` is a statement about this route, not a
                # default: /verdict is the button a person clicks. The bulk
                # route below says something different about itself, which is
                # the whole point of recording it.
                data = _save_verdict(
                    self.decoded_dir, flight, idx, verdict, note,
                    source="human", reviewer=self._reviewer_for(body),
                    queue=body.get("queue"), comment=body.get("comment"), phase=phase,
                    habit=habit)
                at = data.get(str(idx), {}).get("at")
                self._send(json.dumps({"ok": True, "count": len(data), "at": at}).encode(),
                           "application/json")
            else:
                indices = body["particle_indices"]
                data = _save_verdicts_bulk(
                    self.decoded_dir, flight, indices, verdict, note,
                    source="bulk-cluster", reviewer=self._reviewer_for(body),
                    queue=body.get("queue"), habit=habit)
                self._send(
                    json.dumps({"ok": True, "count": len(data),
                               "n_labeled": len(indices)}).encode(),
                    "application/json",
                )
        except Exception as e:  # local dev tool: surface the error, don't crash the server
            self._send(f"<pre>{html.escape(f'{type(e).__name__}: {e}')}</pre>".encode(),
                       status=500)

    # ---- rendering ----

    def _render_diodes(self, flight: str, stride: int, limit: int) -> bytes:
        """The diode-uniformity page for one flight.

        A stuck diode shadows every slice it appears in, so it reads as a
        particle edge in every image that crosses it -- and nothing in
        `imgProc_sm` can see that, because each particle is judged on its own
        silhouette. The signature exists only at flight scale, which is what
        this page shows.

        Requires the decode (`.H.nc` from v3.5, `.H.cdf` from v3.1.4) as well as the
        proc file, since the
        silhouettes live in the decode. A flight whose decode has been reclaimed
        says so rather than rendering an empty chart.
        """
        from .diode_report import (
            NOT_BUILT,
            SPEC_NOISY_DIODE,
            flag_noisy_diodes,
            report_from_files,
        )

        paths = self._flights()[flight]
        image = paths.get("image")
        if image is None or not Path(image).exists():
            return _page(
                f"<h1>{html.escape(flight)}</h1><p class='muted'>This page needs "
                f"the decode (<code>.H.nc</code> from v3.5, <code>.H.cdf</code> from "
                f"v3.1.4) as well as the proc file, "
                f"because the silhouettes live in the decode. This flight's "
                f"decode is not on disk -- it was probably reclaimed after "
                f"processing.</p>", title=f"Diodes -- {flight}")

        # `_NC_LOCK` for the same reason every other netCDF read here takes
        # it: the reads are serialised, and this one walks a whole flight.
        with _NC_LOCK:
            report = report_from_files(image, paths["proc"], stride=stride,
                                       limit=limit)
        flagged, threshold, mean = flag_noisy_diodes(report)

        rows = [
            f"<p>{html.escape(report.summary()).replace(chr(10), '<br>')}</p>",
            f"<p class='muted'>sampled every {stride} particle(s), "
            f"limit {limit:,} -- the sampling is part of the number</p>",
            render_occupancy_svg(report.occupancy, flagged),
            f"<h2>Noisy-diode test</h2><p class='muted'>"
            f"{html.escape(SPEC_NOISY_DIODE.source)}</p>",
            f"<p>mean images per diode {mean:,.1f}; threshold {threshold:,.1f}</p>",
        ]
        if flagged.size == 0:
            rows.append("<p>No diode exceeds the threshold.</p>")
        else:
            names = ", ".join(str(int(i) + 1) for i in flagged)
            rows.append(f"<p><b>{flagged.size} diode(s) flagged (1-based): "
                        f"{names}</b></p>")
            # Beside the flags, not beneath them: a flagged diode is where a
            # reader stops reading.
            rows.append(f"<p class='muted'>{html.escape(SPEC_NOISY_DIODE.m_definition_note)}</p>")
            rows.append("<p class='muted'>This is a whole-flight mean, not the "
                        "manual's rolling window, so a diode noisy for only part "
                        "of the flight is diluted: it under-reports.</p>")
        rows.extend(self._intarr_panel(paths["proc"]))
        rows.extend(self._rate_panel(flight, paths["proc"]))
        rows.append("<p class='muted'>Not built: "
                    + ", ".join(sorted(NOT_BUILT))
                    + " -- see arrayprobe.diode_report.NOT_BUILT.</p>")
        return _page(f"<h1>Diodes -- {html.escape(flight)}</h1>" + "".join(rows),
                     title=f"Diodes -- {flight}")

    def _render_strip(self, flight: str, rec: int, n: int, by: str, *,
                      target: int | None = None, dt: int | None = None,
                      t: str = "") -> bytes:
        """The record-strip view: ``n`` whole records, particles in place.

        :mod:`arrayprobe.diagnostic_views` does the reading and drawing; this only
        routes, links each particle row to its own page, and adds the paging links.
        Like the diode page it needs the decode (``.H.nc`` or ``.H.cdf``), and says so when the
        decode has been reclaimed rather than drawing an empty buffer.

        ``target`` (seconds of day) moves ``rec`` to the first record whose particles are stamped
        at or after it; ``dt`` does the same from the time of ``rec`` plus ``dt`` seconds. Both
        read the proc file's ``Time`` and ``parent_rec_num`` as stored. A time the file does not
        reach leaves ``rec`` where it was and says why above the strip.
        """
        from .diagnostic_views import record_strip, record_strip_html

        paths = self._flights()[flight]
        image = paths.get("image")
        esc = html.escape(flight)
        if image is None or not Path(image).exists():
            return _page(
                f"<h1>{esc}</h1><p class='muted'>The record strip needs the decode "
                f"(<code>.H.nc</code> from v3.5, <code>.H.cdf</code> from v3.1.4), "
                f"because the records live in the decode. This "
                f"flight's decode is not on disk.</p>", title=f"Strip -- {flight}")
        if by not in ("reject", "habit"):
            by = "reject"
        message = ""
        try:
            with _NC_LOCK, netCDF4.Dataset(str(image)) as im, \
                    netCDF4.Dataset(str(paths["proc"])) as pr:
                total = int(im.variables["data"].shape[0])
                if target is not None or dt is not None:
                    try:
                        if "Time" not in pr.variables:
                            raise ValueError("this proc file carries no Time variable, so "
                                             "a record cannot be found by time")
                        prn = pr.variables["parent_rec_num"][:]
                        hhmmss = pr.variables["Time"][:]
                        if target is None:
                            target = record_seconds(prn, hhmmss, rec) + (dt or 0)
                        rec = record_at_time(prn, hhmmss, target)
                    except ValueError as exc:
                        message = str(exc)
                strip = record_strip(im, pr, rec, n, colour_by=by)
        except ValueError as exc:
            return _page(f"<h1>{esc}</h1><p class='muted'>{html.escape(str(exc))}</p>",
                         title=f"Strip -- {flight}")
        last = strip.records[-1]
        nav = [f"<a href='/flight/{esc}'>&larr; {esc}</a>"]
        if rec > 1:
            nav.append(f"<a href='/strip/{esc}?rec={max(1, rec - n)}&n={n}&by={by}'>"
                       f"&larr; earlier</a>")
        if last < total:
            nav.append(f"<a href='/strip/{esc}?rec={last + 1}&n={n}&by={by}'>later &rarr;</a>")
        other = "habit" if by == "reject" else "reject"
        nav.append(f"<a href='/strip/{esc}?rec={rec}&n={n}&by={other}'>colour by {other}</a>")
        body = record_strip_html(
            strip, title=f"Records {rec}-{last} of {total:,}",
            link_particle=lambda i: f"/particle/{flight}/{i}")
        timebar = strip_time_nav_html(flight, rec, n, by, t=t, message=message)
        return _page(f"<p>{' &middot; '.join(nav)}</p><h1>Strip -- {esc}</h1>"
                     f"{timebar}{body}", title=f"Strip -- {flight}")

    def _intarr_panel(self, proc_path) -> list[str]:
        """The inter-arrival histogram, its double-Poisson fit, and the thresholds.

        Composed from `intarr_analysis`, which is oracle-tested; nothing is
        recomputed here. One population over the whole file rather than the
        source's five blocks -- this is a picture of the flight, not a
        reproduction of `sizeDist`'s per-block thresholds, and saying which it
        is matters more than matching the block structure.

        **Why it is worth a panel at all.** `block_thresholds` falls back to
        `DEFAULT_THRESHOLD` when the fit returns a NaN, or when no bin lies
        between the two fitted taus -- and the output file records the number
        without recording that it is a fallback. A threshold from a failed fit
        and one from a good fit are identical in the file and obviously
        different here.

        Failures are reported rather than raised: a diagnostic page that 500s
        because one optional panel could not read a variable is worse than one
        that says so and still shows the diodes.
        """
        import numpy as np

        from .intarr import bimodal_model
        from .intarr_analysis import HIST_BINS, block_thresholds, inter_arrival

        def whole_file_histogram():
            # The panel is a whole-flight histogram, so the whole clock is read -- once per
            # file (2026-10-01 memory incident), held as its few-kB result in _PANEL_CACHE.
            import netCDF4

            with _NC_LOCK, netCDF4.Dataset(str(proc_path)) as ds:
                ds.set_auto_maskandscale(False)
                if "Time_in_seconds" not in ds.variables:
                    return None
                seconds = np.asarray(ds.variables["Time_in_seconds"][:]).reshape(-1)
            int_arr = inter_arrival(seconds)
            finite = int_arr[np.isfinite(int_arr)]
            counts, _ = np.histogram(finite, bins=HIST_BINS)
            return counts, int(finite.size)

        try:
            held = _PANEL_CACHE.get_or_build(
                ("intarr",) + _file_key(proc_path), whole_file_histogram)
        except Exception as exc:                       # noqa: BLE001 -- a viewer
            return [f"<h2>Inter-arrival</h2><p class='muted'>could not read the "
                    f"particle clock: {html.escape(type(exc).__name__)}</p>"]
        if held is None:
            return ["<h2>Inter-arrival</h2><p class='muted'>this proc "
                    "file has no <code>Time_in_seconds</code>, so there "
                    "is no inter-arrival to plot</p>"]
        counts, n_finite = held
        centres = HIST_BINS[:-1] + np.diff(HIST_BINS) / 2
        threshold, ww, ak, tau = block_thresholds(counts)
        fitted = (None if tau is None or np.isnan(np.asarray(tau)).any()
                  else bimodal_model(tau, centres))

        marks = [("2 x min(tau)", threshold), ("fit minimum", ww),
                 ("observed minimum", ak)]
        body = [
            "<h2>Inter-arrival</h2>",
            f"<p class='muted'>{n_finite:,} finite gap(s) over the whole "
            f"file, as one population -- not the five blocks `sizeDist` uses, "
            f"so these thresholds describe the flight rather than reproducing "
            f"any run's own</p>",
            render_intarr_svg(counts, centres, fitted, marks),
            "<p>" + "; ".join(f"{label} {value:.3g} s" for label, value in marks)
            + "</p>",
        ]
        if tau is not None and not np.isnan(np.asarray(tau)).any():
            body.append(f"<p class='muted'>tau = "
                        f"{', '.join(f'{t:.4g}' for t in np.asarray(tau))}</p>")
        return body

    def _rate_panel(self, flight: str, proc_path) -> list[str]:
        """Particles per second, with TAS overlaid when the sidecar is present.

        Rate and airspeed set the sample volume between them, so a rate that
        moves while TAS does not is the shape of an instrument problem rather
        than a cloud. Reports its own failures rather than raising, like the
        other panels here: a diagnostic page that 500s over one optional
        section is worse than one that says what is missing.
        """
        import numpy as np

        from arrayprobe_uiops.sizedist_core import _hhmmss_to_insec

        from .diagnostic_views import per_second_counts

        def whole_file_rate():
            # Particles per second over the whole flight: the whole clock is read once per
            # file (2026-10-01 memory incident) and held as (seconds, counts) in _PANEL_CACHE.
            import netCDF4

            with _NC_LOCK, netCDF4.Dataset(str(proc_path)) as ds:
                ds.set_auto_maskandscale(False)
                if "Time" not in ds.variables:
                    return None
                hhmmss = np.asarray(ds.variables["Time"][:]).reshape(-1).astype(float)
            return per_second_counts(hhmmss)

        try:
            held = _PANEL_CACHE.get_or_build(("rate",) + _file_key(proc_path), whole_file_rate)
        except Exception as exc:                       # noqa: BLE001 -- a viewer
            return [f"<h2>Particles per second</h2><p class='muted'>could not "
                    f"read the particle clock: {html.escape(type(exc).__name__)}</p>"]
        if held is None:
            return ["<h2>Particles per second</h2><p class='muted'>this "
                    "proc file has no <code>Time</code> variable</p>"]
        seconds, counts = held
        if seconds.size == 0:
            return ["<h2>Particles per second</h2><p class='muted'>no finite "
                    "particle times</p>"]

        tas_seconds = tas_values = None
        tas_csv = Path(proc_path).parent / f"{flight}.tas.csv"
        if tas_csv.exists():
            try:
                from .readers.tasinfo import load_tas_info

                tas_hhmmss, tas_values = load_tas_info(tas_csv)
                tas_seconds = _hhmmss_to_insec(np.asarray(tas_hhmmss, dtype=float))
            except Exception:                          # noqa: BLE001 -- a viewer
                tas_seconds = tas_values = None

        return [
            "<h2>Particles per second</h2>",
            render_rate_svg(seconds, counts, tas_seconds, tas_values),
        ]

    def _render_index(self) -> bytes:
        # Deliberately does NOT open any proc file: some run into the
        # multi-GB range (a full flight's worth of particles), and reading
        # image_auto_reject out of every one of them synchronously, on every
        # load of "/", was slow enough to time out real requests during
        # testing. File size (a stat() call, not a netCDF open) is the only
        # per-flight signal shown here; per-flight particle/accepted counts
        # are computed lazily on the flight page itself, one file at a time.
        flights = self._flights()
        rows = []
        for name, paths in flights.items():
            # _discover_flights' regex is unrestricted, so a proc.<anything>.H.nc filename
            # becomes the flight name verbatim -- escape before it reaches HTML, even
            # though every real flight in this project is plain ASCII digits/letters.
            name_html = html.escape(name)
            stamp = paths.get("stamp")
            engine = html.escape(stamp.engine if stamp and stamp.engine else "unrecorded")
            profile = html.escape(stamp.profile if stamp and stamp.profile else "-")
            if paths["image"] is None:
                rows.append(
                    f"<tr><td>{name_html}</td>"
                    f"<td colspan=4 class=muted>no matching raw/image file found</td></tr>"
                )
                continue
            size_gb = paths["proc"].stat().st_size / 1e9
            # One corrupt sidecar must not take the whole index down with it --
            # the other flights are still browsable, and the row is the right
            # place to say so.  Every other caller lets VerdictStoreError
            # propagate, which is what makes a *save* refuse.
            try:
                labeled = f"{len(_load_verdicts(self.decoded_dir, name))} labeled locally"
            except VerdictStoreError as e:
                labeled = (f"<span class=bad>verdict file unreadable</span>"
                           f"<br><span class=muted>{html.escape(str(e))}</span>")
            rows.append(
                f"<tr><td><a href='/flight/{name_html}?group=accepted'>{name_html}</a></td>"
                f"<td>{size_gb:.2f} GB proc file</td>"
                f"<td>{engine}</td><td>{profile}</td>"
                f"<td>{labeled}</td></tr>"
            )
        no_flights = (
            "<tr><td colspan=5 class=muted>No proc.*.H.nc files found in this directory.</td></tr>"
        )
        body = f"""
{self._state_file_panel()}
{self._queue_progress_panel()}
<p><a href="/run">Run a flight</a> -- write a run's configuration and start
<code>arrayprobe run</code> or <code>arrayprobe soda2 run</code> from the browser.</p>
<h2>Flights</h2>
<p class="muted">Browse and label any particle in any decoded flight.
Particle counts load lazily per flight (some proc files are multi-GB) --
click a flight to see them.</p>
<table class="flights">
<thead><tr><th>Flight</th><th>Proc file size</th><th>Engine</th><th>Profile</th>
<th>Labeled</th></tr></thead>
<tbody>{"".join(rows) or no_flights}</tbody>
</table>
{self._refused_panel()}"""
        return _page(body, intro=True, decoded_dir=self.decoded_dir)

    def _state_file_panel(self) -> str:
        """The start-up prompt for the state-variable file, shown until one is loaded.

        Neither ``--state-file`` nor ``--met-dir`` gave the server a temperature source, so the
        index asks for the file's path (and, optionally, the variable). The server opens it and
        chooses the variables by content (:func:`triage_context.detect_state_variables`); a
        refusal is shown under the form with the candidates it found. Once a state file is
        loaded, the panel names the file and the variable it used instead."""
        if isinstance(self.met, StateFile):
            return (
                '<p class="state-file-loaded muted">State-variable file loaded: '
                f"{html.escape(self.met.path.name)}, "
                f"{html.escape(str(self.met.VARIABLE))}</p>"
            )
        if self.met is not None:
            return ""
        return """<section class="state-file">
<h2>State-variable file</h2>
<p class="muted">The particle page shows the air temperature at each particle's second once a
state-variable file is loaded (a netCDF with a temperature in degC or K and a CF time axis).
Leave the variable empty to choose it from the file's units and names.</p>
<form id="state-file-form">
<label>File <input type="text" name="path" size="60" placeholder="path to a netCDF file"></label>
<label>Variable <input type="text" name="var" size="18" placeholder="optional"></label>
<button type="submit">Load</button>
</form>
<p id="state-file-msg" class="muted"></p>
<script>
document.getElementById('state-file-form').addEventListener('submit', function (ev) {
  ev.preventDefault();
  var f = ev.target, msg = document.getElementById('state-file-msg');
  fetch('/state-file', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({path: f.path.value, var: f.var.value || null})})
    .then(function (r) { return r.text().then(function (t) { return [r.ok, t]; }); })
    .then(function (res) { if (res[0]) { location.reload(); } else { msg.textContent = res[1];
      msg.className = 'bad'; } });
});
</script>
</section>"""

    def _post_state_file(self, body: dict) -> None:
        """Load the state-variable file the index form names; 400 with the reason if refused."""
        path = str(body.get("path") or "").strip().strip('"')
        var = body.get("var") or None
        if not path:
            self._send(b"a file path is required", "text/plain; charset=utf-8", status=400)
            return
        try:
            met = StateFile(Path(path), var)
        except StateFileError as e:
            self._send(str(e).encode(), "text/plain; charset=utf-8", status=400)
            return
        TriageServer.met = met
        self._send(json.dumps({"file": str(met.path), "variable": met.VARIABLE}).encode(),
                   "application/json")

    def _refused_panel(self) -> str:
        """The proc files this server declined to index, by name and state.

        **Listed, never silently dropped.** A refusal the user cannot see is indistinguishable
        from a file that was never there, and "the product simply did not appear" is how the
        hardlink incident stayed invisible. The panel says what to do about it, because a
        refusal with no route forward is just an obstacle.
        """
        refused = _refused_flights(self.decoded_dir, self.accept_unstamped)
        if not refused:
            return ""
        rows = "".join(
            f"<tr><td>{html.escape(name)}</td><td>{html.escape(st)}</td></tr>"
            for name, st in refused
        )
        return f"""
<h2>Refused: no provenance</h2>
<p class="muted">{len(refused)} proc file(s) in this directory carry no <code>.call</code>
sidecar recording which engine and profile wrote them, so they are not indexed for labelling:
a verdict attached to a product of unknown configuration cannot be reattributed later. Run
<code>arrayprobe provenance &lt;file&gt;</code> to see what each one does record. To review them
anyway, restart with <code>--accept-unstamped</code>.</p>
<table class="flights">
<thead><tr><th>File</th><th>State</th></tr></thead>
<tbody>{rows}</tbody>
</table>"""

    def _render_flight(self, flight: str, group: str, page: int, per_page: int = 60,
                       want_pieces: int | None = None, want_agreement: bool = False,
                       want_count: str | None = None) -> bytes:
        flights = self._flights()
        if flight not in flights or flights[flight]["image"] is None:
            return _page(f"<p>Flight {html.escape(str(flight))!r} not found or has no "
                        f"matching image file.</p>")
        proc_path = flights[flight]["proc"]
        verdicts = _load_verdicts(self.decoded_dir, flight)
        idx_sorted = _selected_particles(self.decoded_dir, flight, proc_path, group)
        # Every remaining use of `flight` in this function is HTML/URL text, not a
        # filesystem lookup -- escape once here rather than at each interpolation site.
        # `_valid_flight` only guarantees the name matches a real proc file; it says
        # nothing about the name being HTML-safe (the flight regex is unrestricted).
        _raw_flight = flight
        flight = html.escape(flight)

        total = len(idx_sorted)
        n_pages = max(1, -(-total // per_page))
        page = max(1, min(page, n_pages))
        page_idx = [int(i) for i in idx_sorted[(page - 1) * per_page: page * per_page]]
        # Counting pieces rebuilds each particle's image, so it runs only on request: the
        # ?pieces= filter counts this page (and narrows it, never the whole group), and
        # ?agreement=1 counts the flight's labelled particles. The default page counts none.
        pbase = f"/flight/{flight}?group={group}&page={page}"
        counts: dict[int, int] = {}
        if want_pieces is not None:
            counts = _piece_counts(flights[_raw_flight], page_idx)
        if want_agreement:
            labelled = [int(k) for k in verdicts if str(k).isdigit()]
            counts.update(_piece_counts(flights[_raw_flight],
                                        sorted(set(labelled) - set(counts))))
            agreement = piece_agreement_html(piece_label_agreement(verdicts, counts))
        else:
            agreement = (f"<p class='muted'><a href='{pbase}&agreement=1'>Compare piece counts "
                         f"with labels</a> (counts every labelled particle's pieces)</p>")
        shown = keep_page_by_pieces(page_idx, counts, want_pieces)
        # The one / two / three-or-more class: like ?pieces=, counted for this page
        # only and only on request (?count=), and it narrows this page. Display only.
        classes: dict[int, str] = {}
        if want_count is not None:
            classes = _count_classes(flights[_raw_flight], shown)
            shown = [i for i in shown if classes.get(i) == want_count]

        cards = []
        for idx in shown:
            n_pc = counts.get(idx) if want_pieces is not None else None
            pc = f"<div class='muted'>{n_pc} pc</div>" if n_pc is not None else ""
            if want_count is not None:
                pc += f"<div class='muted'>{count_class_html(classes.get(idx))}</div>"
            v = verdicts.get(str(idx))
            # Escaped even though VALID_VERDICTS gates every value written from now on --
            # a sidecar file written before that validation existed, or edited by hand,
            # could still carry anything.
            v_verdict = html.escape(str(v["verdict"])) if v else ""
            cls = f"v-{v_verdict}" if v_verdict in VALID_VERDICTS else ""
            badge = f"<span class='badge'>{v_verdict[:1].upper()}</span>" if v_verdict else ""
            cards.append(
                f"<div class='pcard {cls}'>{badge}<a href='/particle/{flight}/{idx}'>"
                f"<img src='/image/{flight}/{idx}.png' loading=lazy>"
                f"<div>#{idx}</div>{pc}</a></div>"
            )
        pieces_bar = ("<span class='muted'>pieces on this page: "
                      + " &middot; ".join(
                          f"<b>{lab}</b>" if want_pieces == w else f"<a href='{href}'>{lab}</a>"
                          for w, lab, href in ((None, "any", pbase),
                                               (1, "1", pbase + "&pieces=1"),
                                               (2, "2+", pbase + "&pieces=2")))
                      + "</span>")
        count_bar = (f"<span class='muted'>{count_filter_bar(pbase, want_count)} "
                     f"(this page) &middot; <a href='{pbase}'>any</a></span>")

        def tab(g, label):
            """One group tab, marked ``active`` when it is the group on screen.

            The link resets to ``page=1``: page numbers are per-group, so
            carrying the current page across a group switch would land the
            viewer on an arbitrary offset or off the end of a smaller group.
            """
            active = "active" if g == group else ""
            return f"<a class='tab {active}' href='/flight/{flight}?group={g}&page=1'>{label}</a>"

        pager = "".join(
            f"<a href='/flight/{flight}?group={group}&page={p}'>"
            f"{'[' + str(p) + ']' if p == page else p}</a>"
            for p in range(max(1, page - 3), min(n_pages, page + 3) + 1)
        )
        cluster_link = (
            f"<a class='tab' href='/clusters/{flight}?group={group}'>Clusters (bulk label)</a>"
            if _cluster_flight is not None
            else "<span class='muted'>Clusters: enhancements_uiops/ not installed</span>"
        )
        overview = _flight_overview_html(
            _flight_index(self.decoded_dir, _raw_flight, proc_path), verdicts)
        body = f"""
<p><a href="/">&larr; all flights</a></p>
<h1>{flight}</h1>
{overview}
{agreement}
<div class="toolbar">{tab('accepted', 'Accepted')}{tab('rejected', 'Rejected')}{tab('all', 'All')}
<span class="muted">{total:,} particles, sorted largest first &middot; page {page}/{n_pages}</span>
{pieces_bar}
{count_bar}
{cluster_link}</div>
<div class="grid">{"".join(cards)}</div>
<div class="pager">{pager}</div>"""
        return _page(body, f"{flight} — Particle Triage")

    def _render_clusters(self, flight: str, group: str, k: int | None) -> bytes:
        if _cluster_flight is None:
            return _page(
                "<p><a href='/'>&larr; all flights</a></p>"
                "<p>Clustering needs the <code>arrayprobe-enhancements</code> package "
                "(<code>particle_clustering.py</code>) installed -- see "
                "<code>enhancements_uiops/README.md</code>.</p>"
            )
        flights = self._flights()
        if flight not in flights or flights[flight]["image"] is None:
            return _page(f"<p>Flight {html.escape(str(flight))!r} not found or has no "
                        f"matching image file.</p>")
        proc_path = flights[flight]["proc"]

        try:
            # nc_lock is scoped INSIDE cluster_flight to just its netCDF4 read,
            # not held for this whole call -- see particle_clustering.py's
            # extract_features docstring for why a whole-call lock here was a
            # real, measured usability regression (multi-minute timeouts under
            # concurrent load, not just a slower request).
            # The engine that wrote the proc picks the feature columns: v3.5 writes no
            # image_diam_circle_fit, so cluster_flight's engine="3.1.4" default raises on a
            # v3.5 proc. A stamp naming no engine is read as v3.1.4 (as _decode_path does).
            stamp = flights[flight].get("stamp")
            engine = stamp.engine if stamp and stamp.engine else "3.1.4"
            result = _cluster_flight(proc_path, group=group, k=k, nc_lock=_NC_LOCK,
                                     engine=engine)
        except ValueError as e:
            return _page(
                f"<p><a href='/flight/{html.escape(flight)}?group={group}'>&larr; "
                f"{html.escape(flight)}</a></p><p>{html.escape(str(e))}</p>"
            )

        verdicts = _load_verdicts(self.decoded_dir, flight)
        flight_js = json.dumps(flight)   # for the fetch() body below -- raw value, JS-safe
        flight = html.escape(flight)     # every remaining use is HTML text/href, not a lookup
        cards = []
        for cid in result.clusters_by_size():
            medoid = result.medoid_particle_index[cid]
            n = result.cluster_size[cid]
            s = result.cluster_stats[cid]
            labeled = sum(1 for i in result.members(cid) if str(int(i)) in verdicts)
            stat_line = " &middot; ".join(
                f"{name.replace('image_', '').replace('_', ' ')}={v:.2f}" for name, v in s.items()
            )
            cards.append(f"""
<div class="ccard" data-cluster="{cid}">
  <a href="/particle/{flight}/{medoid}"><img src="/image/{flight}/{medoid}.png" loading=lazy></a>
  <div class="n">Cluster {cid} &mdash; {n:,} particles</div>
  <div class="muted" style="font-size:0.72rem">medoid #{medoid} &middot;
    {labeled}/{n} already labeled</div>
  <div class="stats">{stat_line}</div>
  <div class="actions">
    <button class="bulk v-artifact" data-cid="{cid}" data-v="artifact">All artifact</button>
    <button class="bulk v-real" data-cid="{cid}" data-v="real">All real</button>
  </div>
  <div class="cstatus" id="cstatus-{cid}"></div>
</div>""")

        members_json = json.dumps(
            {str(cid): [int(i) for i in result.members(cid)] for cid in result.clusters_by_size()}
        )
        body = f"""
<p><a href="/flight/{flight}?group={group}">&larr; {flight}</a></p>
<h1>{flight} — clusters ({group})</h1>
<p class="muted">k={result.k}, chosen automatically from {len(result.particle_indices):,}
{group} particles. Each card shows the cluster <b>medoid</b> (the real particle nearest that
cluster's center in standardized shape/size feature space) &mdash; not an averaged composite,
which would blur exactly the detail (holes, ragged edges) an artifact call depends on.
"All artifact" / "All real" labels <b>every particle in the cluster</b> in one write, via
<code>/verdict_bulk</code>. Review the medoid image before bulk-labeling a cluster you have
not looked at.</p>
<div class="cgrid">{"".join(cards)}</div>
<script>
var MEMBERS = {members_json};
document.querySelectorAll('button.bulk').forEach(function(b) {{
  b.addEventListener('click', function() {{
    var cid = b.dataset.cid, v = b.dataset.v;
    var members = MEMBERS[cid];
    var status = document.getElementById('cstatus-' + cid);
    status.textContent = 'Saving ' + members.length + '...';
    fetch('/verdict_bulk', {{method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{flight: {flight_js}, particle_indices: members, verdict: v,
        note: 'cluster bulk label (k=' + {result.k} + ', cluster ' + cid + ')'}})}})
      .then(function(r) {{ return r.json(); }})
      .then(function(r) {{
        status.textContent = 'Saved: ' + r.n_labeled + ' particles labeled ' + v + '.';
      }})
      .catch(function(e) {{ status.textContent = 'Error: ' + e; }});
  }});
}});
</script>"""
        return _page(body, f"{flight} clusters — Particle Triage")

    def _render_image(self, flight: str, idx: int, crop: bool,
                      gap: int = PIECE_GAP_DIODES) -> bytes:
        # Object-oriented API (Figure/FigureCanvasAgg) deliberately, NOT pyplot.
        # ThreadingHTTPServer runs one thread per request, and pyplot keeps a
        # single global figure-manager registry shared across every thread --
        # two concurrent renders (routine: any page with more than one <img>
        # loads them in parallel) can corrupt that shared native state and
        # crash the whole process with "Windows fatal exception: access
        # violation" (confirmed from this exact crash's own faulthandler dump,
        # both threads inside this function). A private Figure has no shared
        # state to corrupt.
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        flights = self._flights()
        paths = flights[flight]
        probe = paths.get("probe", "2DS")
        if probe not in DRAWABLE_PROBES:
            # Never raise into an <img> request: a broken-image icon (or a
            # generic 500 page rendered as an image) is worse than a picture
            # that plainly says it is not the real reconstruction.
            return self._not_drawable_image_png(probe)
        with (
            _NC_LOCK,
            netCDF4.Dataset(paths["image"]) as img_ds,
            netCDF4.Dataset(paths["proc"]) as proc_ds,
        ):
            c = reconstruct_particle_image(img_ds, proc_ds, idx, probe=probe)
            if crop:
                c = crop_to_content(c)
        fig = particle_figure(c, IMGPROC_CONFIG[probe].ds * 1000.0, Figure,
                              parts=particle_parts(c, gap=gap))
        FigureCanvasAgg(fig)
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        return buf.getvalue()

    @staticmethod
    def _not_drawable_image_png(probe: str) -> bytes:
        """What ``/image`` returns for a probe outside :data:`DRAWABLE_PROBES`,
        instead of calling :func:`reconstruct_particle_image` and letting its
        ``ValueError`` reach the request. The explanation text is baked into
        the image itself (unlike :func:`arrayprobe.render.unverified_placeholder_png`,
        this route already pays matplotlib's cost per request, so there is no
        contact-sheet-scale reason to keep it text-free here)."""
        import textwrap

        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        fig = Figure(figsize=(4.4, 2.8), dpi=110, facecolor="#fdf3d8")
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        ax.axis("off")
        wrapped = "\n".join(textwrap.wrap(_not_drawable_message(probe), width=40))
        ax.text(0.5, 0.5, wrapped, ha="center", va="center", fontsize=7.5,
                color="#8a6415", transform=ax.transAxes, wrap=True)
        fig.tight_layout(pad=0.3)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
        return buf.getvalue()

    def _render_thumb(self, flight: str, idx: int) -> bytes:
        """A matplotlib-free PNG, for the contact sheet and
        anywhere a page shows many particles at once. Not a resize of
        :meth:`_render_image` -- it never opens matplotlib at all, which is
        the entire point (``_render_image``'s private-``Figure`` cost is what
        makes 200 of them ~10 s; :func:`particle_thumbnail_png` is the same
        ``zlib``/``struct`` writer :func:`render_flight_to_disk` already uses
        for a whole flight, no new dependency).
        """
        flights = self._flights()
        paths = flights[flight]
        probe = paths.get("probe", "2DS")
        if probe not in DRAWABLE_PROBES:
            return unverified_placeholder_png()
        with (
            _NC_LOCK,
            netCDF4.Dataset(paths["image"]) as img_ds,
            netCDF4.Dataset(paths["proc"]) as proc_ds,
        ):
            return particle_thumbnail_png(img_ds, proc_ds, idx, probe=probe)

    def _render_sheet(self, flight: str, group: str, page: int, per_page: int = 200) -> bytes:
        """The `/sheet` contact sheet: many thumbnails, one page, no
        matplotlib in the request path. Particle selection reuses
        :func:`_selected_particles` (the same cached index `_render_flight`
        uses) rather than a second netCDF read."""
        flights = self._flights()
        if flight not in flights or flights[flight]["image"] is None:
            return _page(f"<p>Flight {html.escape(str(flight))!r} not found or has no "
                        f"matching image file.</p>")
        proc_path = flights[flight]["proc"]
        idx_sorted = _selected_particles(self.decoded_dir, flight, proc_path, group)
        flight_html = html.escape(flight)

        total = len(idx_sorted)
        n_pages = max(1, -(-total // per_page))
        page = max(1, min(page, n_pages))
        page_idx = idx_sorted[(page - 1) * per_page: page * per_page]

        cards = "".join(
            f"<div class='pcard'><a href='/particle/{flight_html}/{int(idx)}'>"
            f"<img src='/thumb/{flight_html}/{int(idx)}.png' loading=lazy>"
            f"<div>#{int(idx)}</div></a></div>"
            for idx in page_idx
        )
        pager = "".join(
            f"<a href='/sheet/{flight_html}?group={group}&page={p}'>"
            f"{'[' + str(p) + ']' if p == page else p}</a>"
            for p in range(max(1, page - 3), min(n_pages, page + 3) + 1)
        )
        body = f"""
<p><a href="/flight/{flight_html}?group={group}">&larr; {flight_html}</a></p>
<h1>{flight_html} &mdash; contact sheet ({group})</h1>
<p class="muted">{total:,} particles, sorted largest first &middot; page {page}/{n_pages}
&middot; {per_page} per page, matplotlib-free thumbnails.</p>
<div class="grid">{cards}</div>
<div class="pager">{pager}</div>"""
        return _page(body, f"{flight_html} sheet — Particle Triage")

    def _verdict_widget(self, flight_raw: str, idx: int, current: str | None,
                         on_saved_js: str = "", queue: str | None = None,
                         current_phase: str | None = None,
                         current_comment: str | None = None,
                         current_at: str | None = None,
                         n_parts: int = 0, current_two=None,
                         current_real_parts=None,
                         parts_gap: int = PIECE_GAP_DIODES,
                         current_habit: str | None = None) -> tuple[str, str]:
        """The verdict buttons + their save-on-click script, shared between the
        plain particle page and the queue particle page so the two never drift
        on how a verdict actually gets POSTed.

        ``current_comment`` and ``current_at`` are the stored record's comment and
        time: the box is pre-filled with the one and the saved state names the
        other. The comment saves on its own through ``/comment`` (button or
        Ctrl+Enter) once the particle has a verdict, and rides the verdict before
        that; ``on_saved_js`` (the queue's move-on) is held while the box holds text
        that is not stored, and runs once it is.

        ``queue`` is the queue this particle was served from, or ``None`` on the
        plain particle page, where the particle came from browsing rather than
        from a sample. It is posted so the stored label says which -- a fraction
        is an estimate only for a sample, and a label made while browsing is not
        one. The reviewer id is NOT posted: it is server state
        (:attr:`reviewer`), so no page can decide whose label this is.

        ``flight_raw`` must be the UNESCAPED flight name (this builds its own
        JSON-safe embed via ``json.dumps``, matching ``_render_particle_page``'s
        JS-context handling). ``on_saved_js`` is extra JS run after a successful
        save (the queue page uses it to auto-advance).
        """
        flight_js = json.dumps(flight_raw)
        # json.dumps(None) is the JS literal `null`, which the server reads back
        # as "no queue" -- the browsing case states itself rather than being the
        # absence of a field.
        queue_js = json.dumps(_recordable_queue(queue) if queue else None)

        def btn(v, label):
            """One verdict button, marked ``sel`` when it is the saved verdict.

            ``v`` goes into a ``data-v`` attribute that the page's script POSTs
            back verbatim, so the values here must stay inside
            :data:`VALID_VERDICTS` -- the server re-checks on write, and a
            button offering anything else would simply fail to save.
            """
            sel = "sel" if current == v else ""
            key = _VERDICT_KEYS[v]
            pressed = "true" if sel else "false"
            return (f"<button class='verdict v-{v} {sel} pbtn' data-v='{v}' data-key='{key}' "
                    f"aria-pressed='{pressed}'>"
                    f"{label} <kbd>{key}</kbd></button>")

        # Every member of VALID_VERDICTS gets a button. `mixed` was added to the
        # vocabulary for two-particle images; leaving it without a
        # button would leave reviewers doing what they did before, which is
        # recording those as `unsure` and poisoning both labels.
        def phase_btn(p, label):
            """One phase button, marked ``sel`` when it is the stored phase."""
            sel = "sel" if current_phase == p else ""
            key = _PHASE_KEYS[p]
            pressed = "true" if sel else "false"
            return (f"<button class='phase {sel} pbtn' data-p='{p}' data-key='{key}' "
                    f"aria-pressed='{pressed}'>"
                    f"{label} <kbd>{key}</kbd></button>")

        # The stored comment pre-fills the box, so re-clicking a verdict sends it back
        # rather than an empty box, and the saved state names the record's time.
        stored_comment = current_comment if isinstance(current_comment, str) else ""
        saved_hms = _saved_time(current_at)
        saved_text = ""
        if stored_comment:
            saved_text = (f"Comment saved {saved_hms} UTC." if saved_hms
                          else "Comment saved.")
        # The phase row comes first: pick it, then the verdict, and both are saved
        # together (the queue page moves on after a verdict). A phase picked after
        # the verdict is saved on its own through /phase, changing nothing else.
        # Two particles: how many of them are real, and which numbered piece(s).
        # Always shown: a count (button or 0/1/2 key) picked before "Two particles" saves that
        # verdict first, then the count (reviewer's request, 2026-10-04). The pieces are
        # numbered on the image in order along the flight (triage_context.particle_parts).
        two_cur = current_two if current_two in (0, 1, 2) else None
        real_cur = {int(x) for x in current_real_parts or [] if str(x).isdigit()}
        count_btns = "".join(
            f"<button type='button' class='two-n {'sel' if two_cur == k else ''} pbtn' "
            f"data-n='{k}' "
            f"data-key='{k}'>{k} real <kbd>{k}</kbd></button>" for k in (0, 1, 2))
        piece_btns = "".join(
            f"<button type='button' class='two-p {'sel' if k in real_cur else ''} pbtn' "
            f"data-p='{k}'>#{k}</button>" for k in range(1, n_parts + 1)) if n_parts > 1 else ""
        piece_html = (f"<span class='muted'>Which piece is real:</span> {piece_btns}"
                      if piece_btns else
                      "<span class='muted'>One connected piece of shadow: no numbers to pick."
                      "</span>")
        two_row = (f"<div class='actions two' id='two-row'"
                   ">"
                   f"<span class='muted'>Two particles: how many real?</span> {count_btns}"
                   f"<div>{piece_html}</div>"
                   "<span class='two-status' id='two-status' role='status'></span></div>")
        phases = (f"<div class='actions phases'><span class='muted'>Phase:</span> "
                  f"{phase_btn('ice', 'Ice')}{phase_btn('drizzle', 'Drizzle')}"
                  f"{phase_btn('unsure', 'Phase unsure')}</div>")
        # The optional habit row (IMPACTS, Schima et al. 2024): offered for a particle whose
        # phase is ice or whose verdict is two particles; the script shows and hides it. It
        # travels with the verdict as ``habit`` and is never required.
        habit_show = current_phase == "ice" or current == "mixed"
        habit_btns = "".join(
            f"<button type='button' class='habit {'sel' if current_habit == h else ''} pbtn' "
            f"data-h='{html.escape(h)}' aria-pressed='{'true' if current_habit == h else 'false'}'>"
            f"{html.escape(h)}"
            + (f" <span class='muted'>{html.escape(HABIT_WORDS[h])}</span>"
               if h in HABIT_WORDS else "") + "</button>"
            for h in _habit_choices())
        habits = (f"<div class='actions habits' id='habit-row'{'' if habit_show else ' hidden'}>"
                  f"<span class='muted'>Habit (optional):</span> {habit_btns}</div>")
        actions = (f"{phases}{habits}<div class='actions'>{btn('artifact', 'Artifact')}"
                   f"{btn('real', 'Real')}{btn('mixed', 'Two particles')}"
                   f"{btn('unsure', 'Unsure')}</div>"
                   f"{two_row}"
                   "<div class='comment'><label for='comment'>Comment "
                   "<span class='muted'>&mdash; optional, for when the verdict alone "
                   "is too blunt. Typed before the verdict, it is saved with it; after, "
                   "<kbd>Ctrl</kbd>+<kbd>Enter</kbd> or Save comment saves it."
                   "</span></label>"
                   f"<textarea id='comment' rows='2' maxlength='{COMMENT_MAX_CHARS}' "
                   "placeholder='e.g. two touching drops, called it real on the larger'"
                   f">{html.escape(stored_comment)}</textarea>"
                   "<div class='comment-row'>"
                   "<button type='button' class='comment-save pbtn' id='comment-save'>"
                   "Save comment <kbd>Ctrl+Enter</kbd></button>"
                   f"<span class='comment-status' id='comment-status' role='status'>"
                   f"{saved_text}</span></div></div>"
                   "<div class='status' id='status' role='status' aria-live='polite'></div>"
                   "<div class='keyhint muted'>Keyboard: "
                   "<kbd>a</kbd> artifact &middot; <kbd>r</kbd> real &middot; "
                   "<kbd>t</kbd> two particles &middot; <kbd>u</kbd> unsure &middot; "
                   "<kbd>i</kbd> ice &middot; <kbd>d</kbd> drizzle &middot; "
                   "<kbd>q</kbd> phase unsure &middot; "
                   "<kbd>Ctrl</kbd>+<kbd>Enter</kbd> saves the comment &middot; "
                   # "prev", not "previous": test_triage_server asserts the word
                   # "previous" is absent on a queue's first item, which is how it
                   # checks there is no back-link. That guard is worth keeping
                   # exactly as it is, so the hint works around it rather than
                   # the other way round.
                   "<kbd>&larr;</kbd>/<kbd>p</kbd> prev &middot; "
                   "<kbd>&rarr;</kbd>/<kbd>n</kbd> next &middot; "
                   "<kbd>Esc</kbd> leaves the comment box so the keys work again</div>")
        phase_js = json.dumps(current_phase if current_phase in VALID_PHASES else None)
        habit_js = json.dumps(current_habit if current_habit in _habit_choices() else None)
        at_js = json.dumps(saved_hms)   # digits and colons, or null: safe in a script
        two_js = json.dumps(two_cur)
        parts_js = json.dumps(sorted(real_cur))
        not_saved_js = json.dumps(
            "Comment not saved — Ctrl+Enter or Save comment saves it.")
        held_js = json.dumps(
            "Comment not saved — Ctrl+Enter saves it, then the queue moves on."
            if on_saved_js else
            "Comment not saved — Ctrl+Enter or Save comment saves it.")
        script = f"""
// One save path: every POST this page makes goes through post(), so the keyboard, the
// verdict buttons and the phase buttons all write the same way.
function post(path, payload) {{
  return fetch(path, {{method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify(payload)}});
}}
// The phase: the stored one, or the one picked on this page. It travels with every
// verdict; picked after the verdict, it is saved on its own through /phase. `busy` counts
// the saves in flight, and every navigation this page starts waits for it to reach zero,
// so leaving the page cannot cancel a label that is still being written.
var phase = {phase_js};
var habit = {habit_js};
var busy = 0;
var verdictInFlight = false;
function goWhenIdle(url) {{
  if (busy > 0) {{ setTimeout(function() {{ goWhenIdle(url); }}, 100); return; }}
  window.location = url;
}}
// The comment box: pre-filled from the stored record, saved on its own through /comment
// (the button or Ctrl+Enter) once the particle has a verdict, and sent with the verdict
// before that. `commentDirty` is true while the box differs from what is stored, and the
// page never moves on while it is: it says so instead, and moves on once the text is saved.
var commentBox = document.getElementById('comment');
var commentStatus = document.getElementById('comment-status');
var commentSaved = commentBox ? commentBox.defaultValue.trim() : '';
var commentAt = {at_js};
var commentDirty = false;
var advanceHeld = false;
function hms(at) {{
  return (typeof at === 'string' && at.length >= 19) ? at.slice(11, 19) : null;
}}
function hasVerdict() {{ return !!document.querySelector('button.verdict.sel'); }}
function showComment(msg, unsaved) {{
  if (!commentStatus) {{ return; }}
  commentStatus.textContent = msg;
  commentStatus.classList.toggle('unsaved', !!unsaved);
}}
function markComment() {{
  commentDirty = !!commentBox && commentBox.value.trim() !== commentSaved;
  if (commentDirty) {{
    showComment(hasVerdict() ? {not_saved_js}
                             : 'Comment will be saved with the verdict.', true);
  }} else if (commentSaved) {{
    showComment('Comment saved' + (commentAt ? ' ' + commentAt + ' UTC' : '') + '.');
  }} else {{
    showComment('');
  }}
}}
function saveComment() {{
  if (!commentBox) {{ return; }}
  // A verdict on its way creates the record this save needs: wait for it.
  if (verdictInFlight) {{ setTimeout(saveComment, 100); return; }}
  if (!hasVerdict()) {{ markComment(); return; }}
  var sent = commentBox.value;
  showComment('Saving comment...', true);
  busy += 1;
  post('/comment', {{flight: {flight_js}, particle_index: {idx}, comment: sent,
      queue: {queue_js}}})
    .then(function(r) {{ if (!r.ok) {{ throw new Error('HTTP ' + r.status); }} return r.json(); }})
    .then(function(r) {{
      commentSaved = sent.trim();
      commentAt = hms(r.at);
      markComment();
      if (!commentSaved && !commentDirty) {{
        showComment('Comment cleared' + (commentAt ? ' ' + commentAt + ' UTC' : '') + '.');
      }}
      if (advanceHeld && !commentDirty) {{ afterSave(); }}
    }})
    .catch(function(e) {{ showComment('Comment not saved: ' + e, true); }})
    .finally(function() {{ busy -= 1; }});
}}
if (commentBox) {{
  commentBox.addEventListener('input', markComment);
  commentBox.addEventListener('keydown', function(e) {{
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {{ e.preventDefault(); saveComment(); }}
  }});
}}
var commentSaveButton = document.getElementById('comment-save');
if (commentSaveButton) {{ commentSaveButton.addEventListener('click', saveComment); }}
markComment();
function afterSave() {{
  // Never move on while the box holds text that is not stored.
  if (commentDirty) {{ advanceHeld = true; showComment({held_js}, true); return; }}
  advanceHeld = false;
  {on_saved_js}
}}
// Two particles: the count (0, 1, 2) and the numbered piece(s) that are real.
var twoRow = document.getElementById('two-row');
var nParts = {n_parts};
var twoN = {two_js};
var realParts = {parts_js};
var twoPending = false;
// A count picked before "Two particles" saves that verdict first, then the count: one step.
var verdictNow = {json.dumps(current)};
var countAfterVerdict = false;
function twoStatus(msg) {{
  var t = document.getElementById('two-status'); if (t) {{ t.textContent = msg; }}
}}
function piecesNeeded() {{
  if (twoN === null || nParts < 2 || twoN === 0) {{ return 0; }}
  if (twoN === 2 && nParts === 2) {{ return 0; }}
  return twoN;
}}
function twoDone() {{
  return twoN !== null && (piecesNeeded() === 0 || realParts.length === piecesNeeded());
}}
function saveTwo() {{
  var parts = (twoN === 2 && nParts === 2) ? [1, 2] : (twoN === 0 ? [] : realParts.slice());
  twoStatus('Saving...');
  busy += 1;
  post('/parts', {{flight: {flight_js}, particle_index: {idx}, two_real: twoN,
      real_parts: (nParts < 2 && twoN > 0) ? null : parts, parts_gap: {int(parts_gap)},
      queue: {queue_js}}})
    .then(function(r) {{
      if (r.status === 409) {{ throw new Error('choose "Two particles" (T) first'); }}
      if (!r.ok) {{ throw new Error('HTTP ' + r.status); }}
      return r.json();
    }})
    .then(function() {{
      var named = parts.length ? ' (#' + parts.join(', #') + ')' : '';
      twoStatus('Saved: ' + twoN + ' real' + named + '.');
      if (twoPending) {{ twoPending = false; afterSave(); }}
    }})
    .catch(function(e) {{ twoStatus('Not saved: ' + e); }})
    .finally(function() {{ busy -= 1; }});
}}
document.querySelectorAll('button.two-n').forEach(function(b) {{
  b.addEventListener('click', function() {{
    twoN = parseInt(b.dataset.n, 10);
    document.querySelectorAll('button.two-n').forEach(function(x) {{ x.classList.remove('sel'); }});
    b.classList.add('sel');
    // The count says how many real particles the image holds (reviewer, 2026-10-04): none
    // real is Artifact, saved as that verdict with no count (the artifacts' number is moot).
    // One real particle in a one-piece image is Real. Two real stays "Two particles" with
    // the count, because the piece-gap scoring reads "Real" as one particle and "Two
    // particles" as two or more, so saving two real particles as Real would lose the count.
    var allReal = twoN === 1 && nParts <= 1;
    var direct = twoN === 0 ? 'artifact' : (allReal ? 'real' : null);
    if (direct) {{
      var vb = document.querySelector("button.verdict[data-v='" + direct + "']");
      if (vb) {{ twoStatus(direct === 'artifact' ? 'None real: saving Artifact...'
                                                : 'All real: saving Real...'); vb.click(); }}
      return;
    }}
    if (verdictNow !== 'mixed') {{
      var mixedBtn = document.querySelector("button.verdict[data-v='mixed']");
      if (mixedBtn) {{
        countAfterVerdict = true;
        twoStatus('Some real: saving "Two particles"...');
        mixedBtn.click();
      }}
      return;
    }}
    if (piecesNeeded() === 0) {{ realParts = []; saveTwo(); }}
    else {{ twoStatus('Pick ' + piecesNeeded() + ' numbered piece(s).'); }}
  }});
}});
document.querySelectorAll('button.two-p').forEach(function(b) {{
  b.addEventListener('click', function() {{
    if (twoN === null) {{ twoStatus('First say how many are real.'); return; }}
    if (piecesNeeded() === 0) {{
      twoStatus(twoN === 0 ? 'None is real: no piece to pick.'
                           : 'Both are real: no piece to pick.');
      return;
    }}
    var k = parseInt(b.dataset.p, 10);
    var at = realParts.indexOf(k);
    if (at >= 0) {{ realParts.splice(at, 1); b.classList.remove('sel'); }}
    else {{ realParts.push(k); b.classList.add('sel'); }}
    if (twoN !== null && piecesNeeded() > 0 && realParts.length === piecesNeeded()) {{ saveTwo(); }}
  }});
}});
function savePhase(then) {{
  var s = document.getElementById('status');
  s.textContent = 'Saving phase...';
  busy += 1;
  post('/phase', {{flight: {flight_js}, particle_index: {idx}, phase: phase,
      queue: {queue_js}}})
    .then(function(r) {{ if (!r.ok) {{ throw new Error('HTTP ' + r.status); }} return r.json(); }})
    .then(function() {{ s.textContent = 'Phase saved (' + phase + ').'; if (then) {{ then(); }} }})
    // A failed phase save stops the queue from moving on, so it is seen, not lost.
    .catch(function(e) {{ s.textContent = 'Error: phase not saved: ' + e; }})
    .finally(function() {{ busy -= 1; }});
}}
function showHabitRow() {{
  var row = document.getElementById('habit-row');
  if (!row) {{ return; }}
  var v = document.querySelector('button.verdict.sel');
  row.hidden = !(phase === 'ice' || (v && v.dataset.v === 'mixed'));
}}
document.querySelectorAll('button.habit').forEach(function(b) {{
  b.addEventListener('click', function() {{
    habit = (habit === b.dataset.h) ? null : b.dataset.h;
    document.querySelectorAll('button.habit').forEach(function(x) {{
      var on = x.dataset.h === habit;
      x.classList.toggle('sel', on);
      x.setAttribute('aria-pressed', on ? 'true' : 'false');
    }});
    var v = document.querySelector('button.verdict.sel');
    var s = document.getElementById('status');
    if (!v) {{ s.textContent = 'Habit chosen; pick a verdict to save both.'; return; }}
    v.click();
  }});
}});
document.querySelectorAll('button.phase').forEach(function(b) {{
  b.addEventListener('click', function() {{
    phase = b.dataset.p;
    showHabitRow();
    document.querySelectorAll('button.phase').forEach(function(x) {{
      x.classList.remove('sel');
      x.setAttribute('aria-pressed', 'false');
    }});
    b.classList.add('sel');
    b.setAttribute('aria-pressed', 'true');
    var s = document.getElementById('status');
    if (verdictInFlight) {{
      s.textContent = 'Phase ' + phase + ' will be saved with the verdict.';
      return;
    }}
    if (!document.querySelector('button.verdict.sel')) {{
      s.textContent = 'Phase ' + phase + ' chosen; pick a verdict to save both.';
      return;
    }}
    savePhase(null);
  }});
}});
document.querySelectorAll('button.verdict').forEach(function(b) {{
  b.addEventListener('click', function() {{
    document.getElementById('status').textContent = 'Saving...';
    var sent = phase;
    // The box's text as it stands: "" clears a stored comment, and a page without the
    // box sends null, which keeps it.
    var typed = (document.getElementById('comment') || {{}}).value;
    verdictInFlight = true;
    busy += 1;
    post('/verdict', {{flight: {flight_js}, particle_index: {idx}, verdict: b.dataset.v,
        queue: {queue_js}, phase: sent, habit: habit,
        comment: typed === undefined ? null : typed}})
      .then(function(r) {{
        if (!r.ok) {{ throw new Error('HTTP ' + r.status); }}
        return r.json();
      }})
      .then(function(r) {{
        document.querySelectorAll('button.verdict').forEach(function(x) {{
          x.classList.remove('sel');
          x.setAttribute('aria-pressed', 'false');
        }});
        b.classList.add('sel');
        b.setAttribute('aria-pressed', 'true');
        var s = document.getElementById('status');
        s.textContent = 'Saved (' + r.count + ' labeled in this flight).';
        verdictInFlight = false;
        if (typed !== undefined) {{ commentSaved = typed.trim(); commentAt = hms(r.at); }}
        markComment();
        // "Two particles" holds the queue until the reviewer says how many are real.
        var then = afterSave;
        verdictNow = b.dataset.v;
        if (twoRow && b.dataset.v === 'mixed' && countAfterVerdict) {{
          countAfterVerdict = false;
          twoPending = true;
          then = function() {{
            if (piecesNeeded() === 0) {{ realParts = []; saveTwo(); }}
            else {{ twoStatus('Pick ' + piecesNeeded() + ' numbered piece(s).'); }}
          }};
        }} else if (twoRow && b.dataset.v === 'mixed' && !twoDone()) {{
          twoPending = true;
          then = function() {{ twoStatus('Now say how many are real.'); }};
        }}
        // A phase picked while the verdict was on its way is saved before moving on.
        if (phase !== sent) {{ savePhase(then); }} else {{ then(); }}
      }})
      .catch(function(e) {{
        verdictInFlight = false;
        document.getElementById('status').textContent = 'Error: ' + e;
      }})
      .finally(function() {{ busy -= 1; }});
  }});
}});
document.querySelectorAll('a[data-nav]').forEach(function(a) {{
  a.addEventListener('click', function(e) {{
    if (busy > 0) {{ e.preventDefault(); goWhenIdle(a.getAttribute('href')); }}
  }});
}});

// Keyboard labelling: a labelling pass is hundreds
// of particles, and reaching for the mouse each time is the whole cost. Keys
// dispatch a CLICK on the existing button rather than POSTing themselves, so
// saving, the selected highlight, queue provenance and auto-advance all stay on
// one code path -- a second path here would be a second thing to keep correct.
document.addEventListener('keydown', function(e) {{
  if (e.ctrlKey || e.metaKey || e.altKey) return;          // leave browser shortcuts alone
  var t = e.target;
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) {{
    // Escape hands the keyboard back, so a reviewer who has just typed a
    // comment can label with a keystroke instead of reaching for the mouse --
    // which is the whole reason the keys exist.
    if (e.key === 'Escape') {{ t.blur(); }}
    return;
  }}
  var k = e.key.toLowerCase();
  var b = document.querySelector("button.verdict[data-key='" + k + "']")
       || document.querySelector("button.phase[data-key='" + k + "']")
       || (twoRow && !twoRow.hidden
           && document.querySelector("button.two-n[data-key='" + k + "']"));
  if (b) {{ e.preventDefault(); b.click(); return; }}
  var dir = (k === 'n' || e.key === 'ArrowRight') ? 'next'
          : (k === 'p' || e.key === 'ArrowLeft') ? 'prev' : null;
  if (dir) {{
    var a = document.querySelector("a[data-nav='" + dir + "']");
    if (a) {{ e.preventDefault(); goWhenIdle(a.getAttribute('href')); }}
  }}
}});"""
        return actions, script

    def _queue_verdicts(self, name: str, flight: str) -> dict:
        """The verdicts a queue's pages show: a blind re-check queue's own file, else the flight's.

        One place, so the index, the progress counter and the resume link cannot read a
        different file from the particle page. Until 2026-10-01 those three read the FIRST
        labels for a re-check queue: its index printed each particle's original verdict
        beside it, which un-blinds the re-check the particle page keeps blind, and its
        counter showed every item labelled before the reviewer began.
        """
        return _load_verdicts(self.decoded_dir, flight, recheck=is_recheck_queue(name))

    def _summary(self, name: str) -> dict:
        """:func:`_queue_summary` for one of this server's queues, through ``_queue_verdicts``."""
        return _queue_summary(name, self.queues[name], self._flights(), self._queue_verdicts)

    def _queue_progress(self, name: str, items: list[dict]) -> tuple[int, int]:
        """``(labelled, total)`` for one queue's items, read from :func:`_queue_summary`."""
        s = _queue_summary(name, items, self._flights(), self._queue_verdicts)
        return s["labelled"], s["n"]

    def _queue_progress_panel(self) -> str:
        """Queue progress on the FRONT page, not one click away.

        Author, 2026-09-16, mid-labelling-pass: *"the progress doesn't properly
        show up on the main page so its confusing"*. A labelling pass is the one
        thing this tool exists for, and the front page showed only per-flight
        label totals -- which count every label in the flight, queued or not --
        with a single unadorned link to the queue list. Someone twenty particles
        into a queue could not see that from here. Each queue's row also shows how
        its labels divide (author, 2026-10-01: *"once labeled, the main review queue
        page should provide a summary of the labeling (number of real, artifact,
        etc)"*).
        """
        if not self.queues:
            return ""
        rows, done_all, total_all = [], 0, 0
        for name in self.queues:
            summary = self._summary(name)
            labeled, n = summary["labelled"], summary["n"]
            done_all += labeled
            total_all += n
            state = "done" if n and labeled >= n else ("part" if labeled else "none")
            rows.append(
                f"<tr class='q-{state}'>"
                f"<td><a href='/queue/{html.escape(name)}'>"
                f"{html.escape(describe_queue(name))}</a>"
                f"<br><span class='qcode'>{html.escape(name)}</span>"
                f"{_purpose_html(getattr(self, 'purposes', {}).get(name))}</td>"
                f"<td class='qbar'>{_queue_summary_html(summary)}</td>"
                f"<td class='qn'>{labeled} / {n}</td></tr>")
        return (
            f"<h2 class='qh'>Review queues &mdash; {done_all} of {total_all} labelled</h2>"
            f"<p class='muted'>Progress counts only particles in that queue. "
            f"<a href='/queue'>Queue list &rarr;</a></p>"
            f"<table class='flights queues'><tbody>{''.join(rows)}</tbody></table>")

    def _render_queue_list(self) -> bytes:
        no_queues = "<tr><td colspan=3 class=muted>No --queue-file given at startup.</td></tr>"
        rows = []
        for name in self.queues:
            summary = self._summary(name)
            rows.append(
                f"<tr><td><a href='/queue/{html.escape(name)}'>"
                f"{html.escape(describe_queue(name))}</a>"
                f"<br><span class='qcode'>{html.escape(name)}</span>"
                f"{_purpose_html(getattr(self, 'purposes', {}).get(name))}</td>"
                f"<td class='qbar'>{_queue_summary_html(summary)}</td>"
                f"<td>{summary['labelled']} / {summary['n']} labeled</td></tr>"
            )
        body = f"""
<p><a href="/">&larr; all flights</a></p>
<h1>Review queues</h1>
<p class="muted">A curated particle list for a specific review pass -- narrower than
"every particle in a flight." Verdicts save to the same per-flight
<code>triage_verdicts/&lt;flight&gt;.json</code> files the rest of this tool uses.</p>
<table class="flights">
<thead><tr><th>Queue</th><th>Labels</th><th>Progress</th></tr></thead>
<tbody>{"".join(rows) or no_queues}</tbody>
</table>"""
        return _page(body, "Review queues")

    def _render_queue_index(self, name: str, order: str = QUEUE_ORDERS[0],
                            want_pieces: int | None = None,
                            want_count: str | None = None) -> bytes:
        items = self.queues[name]
        rows = []
        any_parsed = False
        flights = self._flights()
        # A view, not a re-ordering: each row keeps its file position (#, URL, label).
        habits = _queue_habits(name, items, flights)
        pieces = _queue_pieces(name, items, flights)
        classes = _queue_count_classes(name, items, flights)
        view = keep_by_count(keep_by_pieces(_queue_order(habits, order), pieces, want_pieces),
                             classes, want_count)
        q = _order_query(order)
        group_sizes: dict[int, int] = {}
        for i in view:
            rank = _HABIT_RANK.get(habits[i], _NO_SHAPE_RANK)
            group_sizes[rank] = group_sizes.get(rank, 0) + 1
        last_rank = None
        for i in view:
            item = items[i]
            if order == "habit":
                rank = _HABIT_RANK.get(habits[i], _NO_SHAPE_RANK)
                if rank != last_rank:
                    last_rank = rank
                    rows.append(
                        f"<tr class='habit-group'><th colspan='11'>"
                        f"{html.escape(HABIT_GROUPS[rank][0])} "
                        f"<span class='muted'>({group_sizes[rank]})</span></th></tr>")
            flight, idx = item["flight"], item["particle_index"]
            # Same resolution the particle page and the progress counter use; an
            # unresolved name here showed every item as unlabelled.
            flight = _resolve_queue_flight(flight, flights) or flight
            verdicts = self._queue_verdicts(name, flight)
            record = verdicts.get(str(idx), {})
            v = record.get("verdict")
            _v_color = {"artifact": "var(--bad)", "real": "var(--accent)",
                       "unsure": "var(--amber)"}.get(v, "inherit")
            dash = "<span class='muted'>—</span>"
            mark = (f"<b style='color:{_v_color}'>{html.escape(_VERDICT_WORDS.get(v, v))}</b>"
                    if v else dash)
            phase = record.get("phase")
            phase_cell = html.escape(_PHASE_WORDS.get(phase, phase)) if phase else dash
            comment = record.get("comment")
            comment_cell = (f"<span title='{html.escape(comment)}'>✎</span>"
                            if comment else "")
            # The note's parts become columns; the note itself stays one hover away.
            # A note parse_note does not recognise is shown as it is, never guessed at.
            raw_note = item.get("note", "")
            parsed = parse_note(raw_note)
            if "code" in parsed or "minR_um" in parsed or "record_time" in parsed:
                any_parsed = True
                minr = parsed.get("minR_um")
                note_cells = (
                    f"<td>{html.escape(str(minr)) if minr is not None else dash}</td>"
                    f"<td>{reject_code_html(parsed.get('code'))}</td>"
                    f"<td>{html.escape(parsed.get('record_time', '')) or dash}</td>")
            else:
                note_cells = (f"<td colspan='3' class='muted' style='font-size:0.8rem'>"
                              f"{html.escape(str(raw_note))}</td>")
            # The habit is not in the note: it is read from the flight's product.
            habit_cell = habit_html(habits[i] or None)
            tip = f" title='{html.escape(str(raw_note))}'" if raw_note else ""
            rows.append(
                f"<tr{tip}><td>{i}</td><td><a href='/queue/{html.escape(name)}/{i}{q}'>"
                f"{html.escape(flight)} #{idx}</a></td><td>{habit_cell}</td>"
                f"<td class='pieces'>{pieces[i] if pieces[i] is not None else dash}</td>"
                f"<td class='particles'>{count_class_html(classes[i])}</td>"
                f"{note_cells}<td>{mark}</td><td>{phase_cell}</td><td>{comment_cell}</td></tr>"
            )
        # Resolved and queue-aware like the rows above: the unresolved ``.H`` name opened
        # no file, so "resume" always went to item 0 (found 2026-10-01).
        # The first unlabelled item in the order shown, so "resume" follows the view.
        first_unlabeled = next(
            (i for i in view
             if str(items[i]["particle_index"])
             not in self._queue_verdicts(
                 name, _resolve_queue_flight(items[i]["flight"], flights)
                 or items[i]["flight"])),
            view[0] if view else 0,
        )
        legend = f"<p class='muted'>{html.escape(_QUEUE_LEGEND)}</p>" if any_parsed else ""
        # Same lookup as the rows, so a re-check queue's summary stays blind too.
        summary_html = _queue_summary_html(
            _queue_summary(name, items, flights, self._queue_verdicts))
        guide = _field_guide_html() if any_parsed or any(habits) else ""
        base = f"/queue/{html.escape(name)}"
        order_switch = (
            f"Shown grouped by habit, each group in queue order. "
            f"<a href='{base}?order=file'>Show in queue order</a>"
            if order == "habit" else
            f"Shown in queue order. <a href='{base}'>Group by habit</a>")
        n_multi = sum(1 for k in pieces if k is not None and k >= 2)
        order_switch += (
            f" · {n_multi} of {len(items)} images have two or more pieces: "
            f"<a href='{base}?pieces=2'>show only those</a> · "
            f"<a href='{base}?pieces=1'>one piece</a> · <a href='{base}'>all</a>"
            f" · {count_filter_bar(base, want_count)}")
        heads = ("#", "Particle", "Habit", "Pieces", "Particles", "Smallest circle (µm)",
                 "Reject code",
                 "Record time", "Your label", "Phase", "Comment")
        head_row = "".join(f"<th>{h}</th>" for h in heads)
        body = f"""
<p><a href="/queue">&larr; all queues</a></p>
<h1>{html.escape(describe_queue(name))}</h1>
{_purpose_html(getattr(self, 'purposes', {}).get(name))}
<p class="muted"><span class="qcode">{html.escape(name)}</span></p>
{guide}
{summary_html}
<p><a href="/queue/{html.escape(name)}/{first_unlabeled}{q}">
Start / resume at the first unlabeled item &rarr;</a></p>
<p class="muted" id="queue-order">{order_switch}</p>
{legend}
<table class="flights">
<thead><tr>{head_row}</tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>"""
        return _page(body, name)

    def _render_queue_particle(self, name: str, pos: int,
                               order: str = QUEUE_ORDERS[0], qs: dict | None = None) -> bytes:
        items = self.queues[name]
        item = items[pos]
        flight, idx = item["flight"], item["particle_index"]
        flights = self._flights()
        flight = _resolve_queue_flight(flight, flights)
        if flight is None:
            return _page(f"<p>Queue item references unknown flight "
                        f"{html.escape(str(item['flight']))!r}. Known flights: "
                        f"{html.escape(', '.join(sorted(flights)) or '(none)')}.</p>")

        with _NC_LOCK, netCDF4.Dataset(flights[flight]["proc"]) as proc_ds:
            info = particle_info(proc_ds, idx)
        # A re-check queue shows only its own store, so the first label cannot bias the second.
        verdicts = _load_verdicts(self.decoded_dir, flight, recheck=is_recheck_queue(name))
        # The pieces are numbered at the page's ?gap= when given, else at the gap the
        # stored real_parts were saved at.
        gap = gap_override(qs or {})
        if gap is None:
            gap = parts_gap_of(verdicts.get(str(idx)))
        extras, parts = _particle_extras(flights[flight], idx, getattr(self, "met", None), gap)
        current = verdicts.get(str(idx), {}).get("verdict")
        current_habit = verdicts.get(str(idx), {}).get("habit")
        current_phase = verdicts.get(str(idx), {}).get("phase")
        current_comment = verdicts.get(str(idx), {}).get("comment")
        current_at = verdicts.get(str(idx), {}).get("at")
        current_two = verdicts.get(str(idx), {}).get("two_real")
        current_real_parts = verdicts.get(str(idx), {}).get("real_parts")
        kv_beside, kv_below = _kv_split_html(_info_with_extras(info, extras))
        partner_html = self._partner_html(item.get("compare"), flights)
        note = html.escape(item.get("note", ""))

        # Previous and next follow the order the index shows (habit groups by default);
        # past the last item, next_pos is len(items), which the checks below read as none.
        habits = _queue_habits(name, items, flights)
        view = _queue_order(habits, order)
        rank = view.index(pos)
        prev_pos = view[rank - 1] if rank > 0 else None
        next_pos = view[rank + 1] if rank + 1 < len(view) else len(items)
        q = _order_query(order)
        next_url = f"/queue/{html.escape(name)}/{next_pos}{q}"

        # The header counts in the order the page is walked, so "Item 12" is the twelfth
        # page the reviewer reaches, and names the habit group under the grouped view.
        header = [f"Item {rank + 1} of {len(items)}",
                  f"{self._summary(name)['labelled']} labelled"]
        if order != "file":
            g = _HABIT_RANK.get(habits[pos], _NO_SHAPE_RANK)
            header.append(f"group {g + 1} of {len(HABIT_GROUPS)}: {HABIT_GROUPS[g][0]}")
        header_html = " &middot; ".join(html.escape(h) for h in header)
        # Skip moves on in the same order without saving; on the last item it returns to
        # the index. It is not a data-nav link, so the n/p keys and their checks see only
        # the ordinary next and prev links.
        skip_url = (next_url if next_pos < len(items)
                    else f"/queue/{html.escape(name)}{q}")
        # goWhenIdle (the widget's script) waits for any save still in flight, so moving
        # on never cancels a phase saved just after the verdict.
        advance_js = (
            f"if ({next_pos} < {len(items)}) {{"
            f" setTimeout(function() {{ goWhenIdle({next_url!r}); }}, 500);"
            f" }}"
        )
        actions_html, script = self._verdict_widget(flight, idx, current, advance_js,
                                                    queue=name, current_phase=current_phase,
                                                    current_habit=current_habit,
                                                    current_comment=current_comment,
                                                    current_at=current_at,
                                                    n_parts=len(parts), current_two=current_two,
                                                    current_real_parts=current_real_parts,
                                                    parts_gap=gap)

        # data-nav is what the keyboard handler in _verdict_widget looks for; the
        # links stay ordinary anchors, so the mouse path is unchanged and the
        # keys simply follow the same href.
        nav = []
        if prev_pos is not None:
            nav.append(f"<a data-nav='prev' href='/queue/{html.escape(name)}/{prev_pos}{q}'"
                       " class='pbtn'>"
                       f"&larr; previous</a>")
        nav.append(f"<a href='/queue/{html.escape(name)}{q}' class='pbtn'>queue index</a>")
        if next_pos < len(items):
            nav.append(f"<a data-nav='next' href='{next_url}' class='pbtn'>"
                       f"next &rarr;</a>")
        flight_html = html.escape(flight)
        nav.append(f"<a href='/strip/{flight_html}?rec={info['parent_rec_num']}' class='pbtn'>"
                   f"this particle's record, in place</a>")
        actions_html = _with_labelled_status(actions_html, verdicts.get(str(idx)))
        # A tall particle's gap choice goes beside the figure, not under it (is_tall_particle).
        tall = is_tall_particle(info)
        tall_cls = " tall" if tall else ""
        gap_row = gap_choice_html(f"/queue/{name}/{pos}", qs, gap)
        gap_under, gap_beside = ("", gap_row) if tall else (gap_row, "")

        body = f"""
<p class="pnav">{" ".join(nav)}</p>
<h1>{html.escape(describe_queue(name))}</h1>
{_purpose_html(getattr(self, 'purposes', {}).get(name))}
{_written_by_html(flights[flight])}
<p class="item-header" id="item-header">{header_html}</p>
<p class="muted"><span class="qcode">{html.escape(name)}</span> &middot;
{flight_html} &middot; particle #{idx}{" &middot; " + note if note else ""}</p>
<div class="detail{tall_cls}">
  <figure class="pimg">{particle_meta_html(info, extras)}
    <img src="/image/{flight_html}/{idx}.png?gap={gap}&amp;crop=0"
    alt="particle {idx} at true aspect">
    {gap_under}
    <figcaption>{html.escape(TRUE_ASPECT_NOTE)}</figcaption></figure>
  <div class="detail-side">
    {actions_html}
    <p class="skip"><a id="skip" data-skip href="{skip_url}">Skip (leave unlabelled)</a></p>
    {gap_beside}
    <div class="kv">{kv_beside}</div>
  </div>
  <div class="detail-more"><div class="kv">{kv_below}</div></div>
</div>
{partner_html}
<script>{script}
// Skip waits for any save still in flight, as the next and prev links do.
document.querySelectorAll('a[data-skip]').forEach(function(a) {{
  a.addEventListener('click', function(e) {{
    if (busy > 0) {{ e.preventDefault(); goWhenIdle(a.getAttribute('href')); }}
  }});
}});</script>"""
        return _page(body, f"{name} #{pos} — {flight}")

    def _partner_html(self, partner, flights) -> str:
        """The same particle in another product, beside the one being labelled (Track V phase
        3's side-by-side view): a queue item from a comparison script names it under
        ``compare``. The verdict still belongs to the queue's own particle."""
        if not isinstance(partner, dict):
            return ""
        pflight = _resolve_queue_flight(partner.get("flight"), flights)
        raw_pidx = partner.get("particle_index")
        if raw_pidx is None:  # int(None) raised the TypeError refused just below
            return ""
        try:
            pidx = int(raw_pidx)
        except (TypeError, ValueError):
            return ""
        if pflight is None:
            return (f"<p class='muted'>Compared particle's flight "
                    f"{html.escape(str(partner.get('flight')))!r} is not in this directory.</p>")
        with _NC_LOCK, netCDF4.Dataset(flights[pflight]["proc"]) as ds:
            pinfo = particle_info(ds, pidx)
        rows = _kv_html(pinfo)
        label = html.escape(str(partner.get("label") or pflight))
        pf = html.escape(pflight)
        return (f"<h2>The same particle in {label}: {pf} #{pidx}</h2>"
                f"{_written_by_html(flights[pflight])}"
                f"<div class='detail'><figure class='pimg'>"
                f"<img src='/image/{pf}/{pidx}.png?crop=0'>"
                f"<figcaption>{html.escape(TRUE_ASPECT_NOTE)}</figcaption></figure>"
                f"<div class='detail-side'><div class='kv'>{rows}</div></div></div>")

    def _render_particle_page(self, flight: str, idx: int, qs: dict | None = None) -> bytes:
        flights = self._flights()
        paths = flights[flight]
        with _NC_LOCK, netCDF4.Dataset(paths["proc"]) as proc_ds:
            info = particle_info(proc_ds, idx)
            # a few extra fields worth showing a human deciding a verdict
            extra = {}
            for name in ("image_area", "image_hollow", "area_hole_ratio", "image_axis_ratio",
                         "percent_shadow_area", "image_touching_edge"):
                if name in proc_ds.variables:
                    extra[name] = float(proc_ds.variables[name][idx])
        verdicts = _load_verdicts(self.decoded_dir, flight)
        # The pieces are numbered at the page's ?gap= when given, else at the gap the
        # stored real_parts were saved at.
        gap = gap_override(qs or {})
        if gap is None:
            gap = parts_gap_of(verdicts.get(str(idx)))
        extras, parts = _particle_extras(paths, idx, getattr(self, "met", None), gap)
        current = verdicts.get(str(idx), {}).get("verdict")
        current_phase = verdicts.get(str(idx), {}).get("phase")
        current_comment = verdicts.get(str(idx), {}).get("comment")
        current_at = verdicts.get(str(idx), {}).get("at")

        cnn_html = ""
        if _cnn_predict is not None:
            try:
                pred = _cnn_predict(flight=flight, particle_index=idx)  # contract TBD when built
                cnn_html = (
                    f"<div class='cnn'><b>CNN suggestion</b> "
                    f"(enhancements, not authoritative): {html.escape(str(pred))}</div>"
                )
            except Exception as e:
                cnn_html = (
                    f"<div class='cnn muted'>CNN available but raised "
                    f"{html.escape(f'{type(e).__name__}: {e}')}</div>"
                )
        else:
            cnn_html = (
                "<div class='cnn muted'>No CNN classifier installed yet "
                "(none has been built yet).</div>"
            )

        kv_beside, kv_below = _kv_split_html(_info_with_extras({**info, **extra}, extras))
        record = verdicts.get(str(idx), {})
        actions_html, script = self._verdict_widget(flight, idx, current,
                                                    current_phase=current_phase,
                                                    current_habit=record.get("habit"),
                                                    current_comment=current_comment,
                                                    current_at=current_at,
                                                    n_parts=len(parts),
                                                    current_two=record.get("two_real"),
                                                    current_real_parts=record.get("real_parts"),
                                                    parts_gap=gap)
        actions_html = _with_labelled_status(actions_html, verdicts.get(str(idx)))
        written_by = _written_by_html(paths)
        gap_html = gap_choice_html(f"/particle/{flight}/{idx}", qs, gap)
        meta_html = particle_meta_html(info, extras)
        flight = html.escape(flight)     # every remaining use is HTML text/href, not a lookup
        # A tall particle's gap choice goes beside the figure, not under it (is_tall_particle).
        tall = is_tall_particle(info)
        tall_cls = " tall" if tall else ""
        gap_under, gap_beside = ("", gap_html) if tall else (gap_html, "")

        body = f"""
<p class="pnav"><a href="/flight/{flight}" class="pbtn">&larr; {flight}</a>
<a href="/strip/{flight}?rec={info['parent_rec_num']}" class="pbtn">this particle's record,
in place</a></p>
<h1>Particle {idx}</h1>
{written_by}
<div class="detail{tall_cls}">
  <figure class="pimg">{meta_html}
    <img src="/image/{flight}/{idx}.png?gap={gap}&amp;crop=0"
    alt="particle {idx} at true aspect">
    {gap_under}
    <figcaption>{html.escape(TRUE_ASPECT_NOTE)}</figcaption></figure>
  <div class="detail-side">
    {actions_html}
    {gap_beside}
    <div class="kv">{kv_beside}</div>
  </div>
  <div class="detail-more"><div class="kv">{kv_below}</div>
    {cnn_html}</div>
</div>
<script>{script}</script>"""
        return _page(body, f"#{idx} — {flight}")


def _labelled_text(record) -> str:
    """What a stored label says, in words: ``Labelled real · ice · 14:02:11 UTC``.

    ``""`` when the particle has no verdict. A phase that is not set says so, and the
    time is the record's own ``at``, left out when the record carries none.
    """
    if not isinstance(record, dict) or not record.get("verdict"):
        return ""
    v, p = str(record["verdict"]), record.get("phase")
    parts = [f"Labelled {_VERDICT_WORDS.get(v, v)}",
             _PHASE_WORDS.get(p, str(p)) if p else "phase not set"]
    hms = _saved_time(record.get("at"))
    if hms:
        parts.append(f"{hms} UTC")
    return " · ".join(parts)


#: The empty status line the verdict widget writes; a stored label is shown inside it.
_STATUS_OPEN = "id='status' role='status' aria-live='polite'>"


def _with_labelled_status(actions_html: str, record) -> str:
    """The widget's HTML with its status line saying how the particle is already labelled.

    The page's script overwrites the line on the next save, so it only ever describes the
    label the page was opened with. If the widget's status line is not where it is
    expected, the words go in a line of their own above it rather than being lost.
    """
    text = _labelled_text(record)
    if not text:
        return actions_html
    if _STATUS_OPEN in actions_html:
        return actions_html.replace(_STATUS_OPEN, _STATUS_OPEN + html.escape(text), 1)
    return f"<p class='status'>{html.escape(text)}</p>{actions_html}"


def run(decoded_dir: Path, port: int = 8765, queue_file: Path | None = None,
        reviewer: str | None = None, accept_unstamped: bool = False,
        met_dir: Path | None = None, state_file: Path | None = None,
        state_var: str | None = None, run_root: Path | None = None):
    """Start the server on localhost and block until interrupted.

    ``run_root`` is the folder whose ``_runs/`` the Run page lists at ``/runs``. Left ``None``,
    the first run launched from ``/run`` sets it to the output folder typed on the form.

    ``accept_unstamped`` indexes products whose provenance is unrecorded. Default False: they
    are refused and named on the index page instead (:func:`_discover_flights`). The banner
    below says which way this server is running, because "my flight is missing" and "my flight
    was refused" need different answers and the terminal is where the user looks first.

    ``reviewer`` is recorded with every label this server writes. It is
    validated here, before the socket is bound, so a malformed id fails at
    startup rather than on the first save in the middle of a pass. Left
    ``None``, the server starts but refuses every label save with HTTP 400 --
    stated in the banner, never filled in from the OS username.

    Binds ``127.0.0.1`` explicitly, never ``0.0.0.0``: this is a local review
    tool with no authentication, and it reads whatever is under
    ``decoded_dir``. The banner it prints names the URL, that directory, and
    which optional pieces are present, so a session's context is visible in the
    terminal rather than assumed.
    """
    TriageServer.decoded_dir = decoded_dir
    TriageServer.reviewer = _clean_label(reviewer, "reviewer")
    TriageServer.accept_unstamped = accept_unstamped
    TriageServer.met = choose_met(met_dir, state_file, state_var)
    queue_data = _load_queue_file(queue_file) if queue_file else {}
    TriageServer.queues = _review_queues(queue_data)
    TriageServer.purposes = _queue_purposes(queue_data)
    TriageServer.second_choices = _second_choices(queue_data)
    TriageServer.run_root = run_root
    server = ThreadingHTTPServer(("127.0.0.1", port), TriageServer)
    print(f"Particle Triage running at http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    print(f"Decoded dir: {decoded_dir}")
    refused = _refused_flights(decoded_dir, accept_unstamped)
    if accept_unstamped:
        print("Provenance: --accept-unstamped -- products with no .call stamp ARE indexed; "
              "labels on them record no engine or profile.")
    elif refused:
        print(f"Provenance: {len(refused)} proc file(s) refused for having no .call stamp "
              f"({', '.join(n for n, _ in refused[:5])}"
              f"{', ...' if len(refused) > 5 else ''}); they are listed on the index page. "
              f"Use --accept-unstamped to review them anyway.")
    else:
        print("Provenance: every proc file in this directory is stamped.")
    if TriageServer.reviewer:
        print(f"Reviewer: {TriageServer.reviewer}  (recorded with every label)")
    else:
        print("Reviewer: NOT SET -- every label save will be refused (HTTP 400). Pass "
              f"--reviewer <id> or set {REVIEWER_ENV}.")
    unrecordable = [n for n in TriageServer.queues if _recordable_queue(n) is None]
    if unrecordable:
        print(f"Queue names that cannot be stored on a label: {', '.join(unrecordable)} "
              "-- their labels will record no queue.")
    if isinstance(TriageServer.met, StateFile):
        print(f"Air temperature: {TriageServer.met.VARIABLE} on "
              f"{TriageServer.met.time_variable} in {TriageServer.met.path}")
    elif TriageServer.met is not None:
        print(f"Air temperature: {len(TriageServer.met)} merged aircraft file(s) in {met_dir}")
    else:
        print("Air temperature: not loaded -- the index page asks for a state-variable file "
              "(or pass --state-file / --met-dir)")
    cnn_status = "available" if _cnn_predict else "not installed (no classifier has been built yet)"
    print(f"CNN suggestions: {cnn_status}")
    if run_root is not None:
        print(f"Run page: http://127.0.0.1:{port}/run  (runs listed from {run_root})")
    else:
        print(f"Run page: http://127.0.0.1:{port}/run  (runs listed from the first run's "
              "output folder; --run-root names one)")
    if TriageServer.queues:
        names = ", ".join(TriageServer.queues)
        print(f"Review queues: {names}  (http://127.0.0.1:{port}/queue)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        # Real incident, 2026-08-27: this server died twice under real use with
        # nothing useful in the log -- serve_forever() itself apparently never
        # raises here (ThreadingHTTPServer's own request-handling threads catch
        # their own exceptions), so if this branch DOES fire it's worth knowing
        # exactly what escaped. sys.stderr.flush() because a process dying right
        # after print() can lose buffered output the caller never sees.
        import sys
        import traceback
        print(f"FATAL: {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.stderr.flush()
        raise
    finally:
        server.server_close()


def choose_met(met_dir: Path | None = None, state_file: Path | None = None,
               state_var: str | None = None) -> MetFolder | StateFile | None:
    """The temperature source: ``--state-file`` when given (it overrides ``--met-dir``), else
    the merged files ``--met-dir`` names by their known file names, else ``None`` -- and then
    the index page asks for a file. A named file that cannot give an unambiguous temperature
    raises :class:`StateFileError` at start-up rather than on the first particle."""
    if state_file is not None:
        return StateFile(Path(state_file), state_var)
    if state_var is not None:
        raise StateFileError("--state-var needs --state-file")
    return MetFolder(met_dir) if met_dir else None


def main(argv=None) -> int:
    """``python -m arrayprobe.triage_server`` -- parse options and start the server.

    Not a console script in ``pyproject.toml``, deliberately: it is a review
    tool that needs a decoded directory to point at, and the module form keeps
    that explicit rather than making it look like a command that works anywhere.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--decoded-dir", type=Path, required=True,
                     help="directory containing proc.*.H.nc files and their decodes "
                          "(*.H.nc from v3.5, *.H.cdf from v3.1.4)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--queue-file", type=Path, default=None,
                     help="JSON file of named curated particle lists for a specific "
                          "review pass -- see _load_queue_file's docstring for the shape")
    ap.add_argument("--reviewer", default=os.environ.get(REVIEWER_ENV),
                     help=f"who is labelling; REQUIRED to save labels and recorded with "
                          f"every verdict (or set {REVIEWER_ENV}). Never guessed: with "
                          f"neither, the server starts but refuses every save (HTTP 400)")
    ap.add_argument("--accept-unstamped", action="store_true",
                     help="index proc files that carry no .call provenance stamp. Without it "
                          "they are refused and listed on the index page under 'Refused: no "
                          "provenance' -- never silently dropped")
    ap.add_argument("--met-dir", type=Path, default=None,
                     help="folder of ARM AAF merged files (enaaafmergedF1.c1.*.nc) for the air "
                          "temperature on the particle page")
    ap.add_argument("--state-file", type=Path, default=None,
                     help="netCDF state-variable file for the air temperature; the variable "
                          "is chosen by units and names unless --state-var names it. "
                          "Overrides --met-dir. With neither, the index page asks for one")
    ap.add_argument("--state-var", default=None,
                     help="the temperature variable in --state-file (default: chosen by content)")
    ap.add_argument("--run-root", type=Path, default=None,
                     help="folder whose _runs/ the Run page lists at /runs (default: the output "
                          "folder of the first run launched from /run)")
    args = ap.parse_args(argv)
    run(args.decoded_dir.resolve(), args.port, args.queue_file, args.reviewer,
        accept_unstamped=args.accept_unstamped, met_dir=args.met_dir,
        state_file=args.state_file, state_var=args.state_var,
        run_root=args.run_root.resolve() if args.run_root is not None else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
