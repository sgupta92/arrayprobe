# SPDX-License-Identifier: BSD-3-Clause
"""Two diagnostic views: the record strip and the one-second comparison.

Visualisation, so core rather than ``enhancements_uiops/`` -- nothing here computes a pipeline
number
or writes one; every function reads files the port already wrote and says what is in them.
Both views are standard library + numpy + netCDF4 only (the PNG is written by hand with
``zlib``, like :func:`arrayprobe.render._png_bytes`), so neither needs the ``viz`` extra.

**The record strip** (:func:`record_strip`, :func:`record_strip_png`, :func:`record_strip_html`).
HydroViewer's view, and the gap
that had been missing from this package:
whole 1700-slice image records stacked one above the next, every particle in place, the
boundary slices between particles marked, and each particle's shadow coloured by its reject code
or its habit. The triage server shows one particle, cropped; this shows the *buffer* -- the
spacing between particles, the particles a record-boundary reset put side by side, and a
shadow that no particle window claims (a slice ``imgProc_sm`` never framed). Every fifth particle
gets a red tick above its first slice, HydroViewer's ``annotate`` aid for lining a strip up
against the per-particle file.

**The one-second comparison** (:func:`compare_second`, :func:`second_comparison_html`). For
validation work: one second of two size-distribution files -- the port's and the archive's --
bin by bin, with the differing cells marked and the particles of that second whose diameter falls
in a differing bin listed beside them, each with its reject code and centre-in flag. It is the
tool a residual root-cause did by hand with ``compare_nc.py`` and a notebook.

**What each view claims, and where a test checks it** (``tests/test_diagnostic_views.py``):

* the strip's shadow inside each particle window is the particle's own silhouette -- asserted
  against :func:`arrayprobe.render.reconstruct_particle_image`, the gallery's path, which decodes
  with ``dec2bin_concat`` where this module unpacks bits; two mechanisms, one answer;
* the strip lists exactly the proc rows whose ``parent_rec_num`` falls in the records shown;
* the PNG decodes back to the index image, and each category's pixel count equals the summed
  shadow of the particles in it;
* the comparison's per-bin values are the files' own, its differing cells are exactly the
  cells that differ, and a particle is listed only if its second and its diameter put it there.
"""

from __future__ import annotations

import html
import os
import struct
import threading
import zlib
from dataclasses import dataclass, field

import numpy as np

from .matlab_compat import HOLROYD_HABITS, REJECT_CODES

__all__ = [
    "BOUNDARY_WORD",
    "SLICES_PER_RECORD",
    "StripParticle",
    "RecordStrip",
    "record_strip",
    "strip_index_image",
    "record_strip_png",
    "record_strip_html",
    "SecondComparison",
    "compare_second",
    "second_comparison_html",
    "per_second_counts",
    "HOLLOW_ACCEPTED_CODES",
    "HOLLOW_VERDICT_MIN_FRACTION",
    "HollowShare",
    "hollow_share",
    "hollow_share_text",
]

#: The 2D-S/HVPS particle-boundary word: a slice in which every word is ``0xAAAA`` separates two
#: particles (``imgProc_sm.m``'s boundary for probetype 2; ``imgproc.py``'s ``cfg.boundary``).
#: Other probe types pass their own to :func:`record_strip`.
BOUNDARY_WORD = 0xAAAA

#: ``ImgBlocklen`` -- every decoded image record is 1700 slices.
SLICES_PER_RECORD = 1700

_ACCEPTED = REJECT_CODES["0"]
_REJECT_BY_VALUE = {v: k for k, v in REJECT_CODES.items()}
_HABIT_BY_VALUE = {v: k for k, v in HOLROYD_HABITS.items()}

# Palette indices below _FIRST_CATEGORY are fixed roles; categories follow in a fixed order.
_BACKGROUND, _SEPARATOR, _BOUNDARY, _UNCLAIMED, _TICK = range(5)
_FIRST_CATEGORY = 5
_ROLE_COLOURS = [
    (255, 255, 255),   # background: an unshadowed diode
    (232, 232, 232),   # separator band between records (and the tick row)
    (0, 190, 200),     # boundary slice: every word is the boundary word
    (150, 150, 150),   # shadow inside no particle window
    (220, 0, 0),       # every-fifth-particle tick
]
#: Category colours in order; the accepted class is always black, so it reads as the particle
#: silhouette every other view here draws.
_CATEGORY_COLOURS = [
    (31, 119, 180), (255, 127, 14), (44, 160, 44), (148, 103, 189), (140, 86, 75),
    (227, 119, 194), (188, 189, 34), (23, 190, 207), (214, 39, 40), (127, 127, 127),
    (174, 199, 232), (255, 187, 120), (152, 223, 138), (197, 176, 213), (196, 156, 148),
]
_ACCEPTED_COLOUR = (0, 0, 0)
_SEPARATOR_ROWS = 4


@dataclass(frozen=True)
class StripParticle:
    """One proc row, placed in its record. Slices are 1-based and inclusive, as ``position`` is."""

    index: int            # 0-based row in the proc file
    record: int           # 1-based ``parent_rec_num``
    first_slice: int
    last_slice: int
    reject: str | None    # ``image_auto_reject`` as its character; ``'0'`` is accepted
    habit: str | None     # ``holroyd_habit`` as its character

    def category(self, colour_by: str) -> str:
        """The class this particle is coloured by: ``'accepted'``, a reject code, or a habit."""
        if colour_by == "reject":
            if self.reject and self.reject in "0HhuR":  # sizeDist.m:1209's accepted set
                return "accepted"
            return f"reject {self.reject or '?'}"
        return f"habit {self.habit or '?'}"


@dataclass(frozen=True)
class RecordStrip:
    """``n`` consecutive image records with their particles in place.

    ``shadow`` is ``(n_records, 1700, n_diodes)``, ``True`` where a diode was shadowed -- the
    same convention as :func:`arrayprobe.render.reconstruct_particle_image`. ``boundary`` is
    ``(n_records, 1700)``, ``True`` on a slice whose every word is the boundary word.
    """

    records: tuple[int, ...]
    shadow: np.ndarray
    boundary: np.ndarray
    particles: tuple[StripParticle, ...]
    colour_by: str = "reject"
    categories: tuple[str, ...] = field(default=())

    def particles_in(self, record: int) -> list[StripParticle]:
        """The particles whose ``parent_rec_num`` is ``record`` (1-based), in proc order."""
        return [p for p in self.particles if p.record == record]


def _shadow_of_block(block: np.ndarray) -> np.ndarray:
    """``(slices, n_words)`` raw words -> ``(slices, 16 * n_words)`` shadow, MSB first.

    ``imgProc_sm.m:266-268`` inverts (``65535 - data``) and reads a ``'0'`` character as shadow;
    that is the same as reading a set bit of the raw word as shadow, which is what this does with
    ``unpackbits`` -- deliberately not ``dec2bin_concat``, so the test that compares the two is
    comparing two mechanisms rather than one.
    """
    words = np.asarray(block).astype(np.int64) & 0xFFFF
    as_bytes = words.astype(">u2").view(np.uint8).reshape(words.shape[0], -1)
    return np.unpackbits(as_bytes, axis=1).astype(bool)


def _char(value, table) -> str | None:
    if value is None:
        return None
    v = float(value)
    if not np.isfinite(v):
        return None
    return table.get(int(v), chr(int(v)) if 32 <= int(v) < 127 else None)


def _first_at_least(var, n: int, value: float) -> int:
    """The first row of the 1-D, non-decreasing ``var`` (length ``n``) whose value is at least
    ``value``, or ``n``: a binary search that reads one element per step, as a one-element slice
    so a stored value reaches the comparison exactly as a whole read would deliver it."""
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi) // 2
        if float(np.asarray(var[mid:mid + 1]).reshape(-1)[0]) < value:
            lo = mid + 1
        else:
            hi = mid
    return lo


#: ``{(proc path, size, mtime_ns): parent_rec_num is finite and non-decreasing}`` -- one bool per
#: proc file, so the scan below runs once per file per process, not once per request.
_RECORD_ORDER_CACHE: dict[tuple, bool] = {}
_RECORD_ORDER_LOCK = threading.Lock()
_ORDER_SCAN_CHUNK = 1 << 20


def _in_record_order(proc_ds, pvar, n: int) -> bool:
    """Whether ``parent_rec_num`` is finite and non-decreasing over the whole file.

    The binary search in :func:`_strip_rows` is only correct on such a file, and a local check of
    the block it finds cannot see disorder elsewhere (a shuffled file can bisect to an empty
    block). So the whole variable is scanned once, in chunks of ``_ORDER_SCAN_CHUNK`` elements --
    bounded memory -- and the answer is cached per file (path, size and mtime), so a server pays
    it once per flight rather than per request.
    """
    key = None
    try:
        path = proc_ds.filepath()
        st = os.stat(path)
        key = (str(path), st.st_size, st.st_mtime_ns)
    except (AttributeError, OSError, ValueError):
        pass
    if key is not None:
        with _RECORD_ORDER_LOCK:
            hit = _RECORD_ORDER_CACHE.get(key)
        if hit is not None:
            return hit
    ordered, prev = True, -np.inf
    for start in range(0, n, _ORDER_SCAN_CHUNK):
        part = np.asarray(pvar[start:start + _ORDER_SCAN_CHUNK]).reshape(-1)
        if part.size and (not np.all(np.isfinite(part)) or part[0] < prev
                          or np.any(np.diff(part) < 0)):
            ordered = False
            break
        if part.size:
            prev = part[-1]
    if key is not None:
        with _RECORD_ORDER_LOCK:
            _RECORD_ORDER_CACHE[key] = ordered
    return ordered


def _strip_rows(proc_ds, first_record: int, last: int):
    """``(lo, hi, parent, position, reject, habit)`` for the proc rows a strip of records
    ``first_record``..``last`` needs, each array starting at proc row ``lo``.

    ``parent_rec_num`` is written in record order, so the rows of a run of records are one
    contiguous block: its bounds are found by binary search (O(log n) one-element reads) and only
    that block of each variable is read. Reading the four variables whole on every request is what
    took the triage server to 44 GB on a 17.8M-particle flight (2026-10-01). A file this does not
    recognise -- ``parent_rec_num`` not 1-D, ``position`` not ``(particles, 2)``, or
    ``parent_rec_num`` not finite and non-decreasing (:func:`_in_record_order`) -- is read whole,
    exactly as before, so the shown content never depends on which path ran.
    """
    pvar = proc_ds.variables["parent_rec_num"]
    posvar = proc_ds.variables["position"]
    rvar = proc_ds.variables.get("image_auto_reject")
    hvar = proc_ds.variables.get("holroyd_habit")
    n = int(pvar.shape[0]) if pvar.ndim == 1 else -1
    sliceable = (n >= 0 and posvar.ndim == 2 and int(posvar.shape[0]) == n
                 and int(posvar.shape[1]) == 2
                 and all(v is None or (v.ndim == 1 and int(v.shape[0]) == n)
                         for v in (rvar, hvar)))
    if sliceable and _in_record_order(proc_ds, pvar, n):
        lo = _first_at_least(pvar, n, first_record)
        hi = _first_at_least(pvar, n, last + 1)
        return (lo, hi, np.asarray(pvar[lo:hi]).reshape(-1),
                np.asarray(posvar[lo:hi, :]).reshape(-1, 2),
                np.asarray(rvar[lo:hi]).reshape(-1) if rvar is not None else None,
                np.asarray(hvar[lo:hi]).reshape(-1) if hvar is not None else None)
    parent = np.asarray(pvar[:]).reshape(-1)
    return (0, parent.size, parent,
            np.asarray(posvar[:]).reshape(-1, 2),
            np.asarray(rvar[:]).reshape(-1) if rvar is not None else None,
            np.asarray(hvar[:]).reshape(-1) if hvar is not None else None)


def record_strip(image_ds, proc_ds, first_record: int, n_records: int = 6, *,
                 colour_by: str = "reject", boundary_word: int = BOUNDARY_WORD) -> RecordStrip:
    """Records ``first_record`` .. ``first_record + n_records - 1`` (1-based) with their particles.

    ``image_ds``/``proc_ds`` are open ``netCDF4.Dataset`` handles on one flight's decoded image
    file and its proc file. The last record shown is clipped to the file's own length, and a
    ``first_record`` outside the file raises, naming the file's range -- a strip of nothing would
    look like an empty buffer, which is a different finding.
    """
    if colour_by not in ("reject", "habit"):
        raise ValueError(f"colour_by must be 'reject' or 'habit', not {colour_by!r}")
    data = image_ds.variables["data"]
    total = int(data.shape[0])
    if not 1 <= first_record <= total:
        raise ValueError(f"record {first_record} is outside this file's 1..{total}")
    if n_records < 1:
        raise ValueError("n_records must be at least 1")
    last = min(total, first_record + n_records - 1)
    records = tuple(range(first_record, last + 1))

    blocks = [np.asarray(data[r - 1, :, :]) for r in records]
    shadow = np.stack([_shadow_of_block(b) for b in blocks])
    boundary = np.stack([np.all((b.astype(np.int64) & 0xFFFF) == boundary_word, axis=1)
                         for b in blocks])

    lo, hi, parent, position, reject, habit = _strip_rows(proc_ds, first_record, last)
    rows = np.nonzero((parent >= first_record) & (parent <= last))[0]
    particles = tuple(
        StripParticle(
            index=int(lo + i), record=int(parent[i]),
            first_slice=int(position[i, 0]), last_slice=int(position[i, 1]),
            reject=_char(reject[i], _REJECT_BY_VALUE) if reject is not None else None,
            habit=_char(habit[i], _HABIT_BY_VALUE) if habit is not None else None)
        for i in rows)
    categories = tuple(sorted({p.category(colour_by) for p in particles},
                              key=lambda c: (c != "accepted", c)))
    return RecordStrip(records, shadow, boundary, particles, colour_by, categories)


def strip_index_image(strip: RecordStrip) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """The strip as a palette-index image and its palette -- what :func:`record_strip_png` encodes.

    Layout: for each record, a band of ``_SEPARATOR_ROWS`` rows (the tick row: red at the first
    slice of every fifth particle, counted across the whole strip from 1) then one row per diode;
    one column per slice. Pixel roles: background, boundary slice, shadow inside no particle
    window, and one colour per category (``strip.categories``, accepted always black).
    """
    n_rec, n_slices, n_diodes = strip.shadow.shape
    band = _SEPARATOR_ROWS + n_diodes
    img = np.full((n_rec * band, n_slices), _BACKGROUND, dtype=np.uint8)
    palette = list(_ROLE_COLOURS)
    colour_of = {}
    others = iter(_CATEGORY_COLOURS * (1 + len(strip.categories) // len(_CATEGORY_COLOURS)))
    for k, cat in enumerate(strip.categories):
        colour_of[cat] = _FIRST_CATEGORY + k
        palette.append(_ACCEPTED_COLOUR if cat == "accepted" else next(others))

    for k, rec in enumerate(strip.records):
        top = k * band
        img[top:top + _SEPARATOR_ROWS, :] = _SEPARATOR
        body = img[top + _SEPARATOR_ROWS: top + band, :]        # (diodes, slices) view
        sh = strip.shadow[k].T                                   # (diodes, slices)
        body[:, strip.boundary[k]] = _BOUNDARY
        body[sh & ~strip.boundary[k][None, :]] = _UNCLAIMED
        for p in strip.particles_in(rec):
            lo, hi = max(p.first_slice, 1) - 1, min(p.last_slice, n_slices)
            window = body[:, lo:hi]
            window[sh[:, lo:hi]] = colour_of[p.category(strip.colour_by)]
    for n, p in enumerate(strip.particles, start=1):
        if n % 5 == 0:
            k = strip.records.index(p.record)
            col = max(p.first_slice, 1) - 1
            img[k * band: k * band + _SEPARATOR_ROWS, col] = _TICK
    return img, palette


def _palette_png(img: np.ndarray, palette) -> bytes:
    """An 8-bit palette PNG (colour type 3) of ``img``; standard library only."""
    height, width = img.shape
    raw = b"".join(b"\x00" + img[row].tobytes() for row in range(height))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    plte = b"".join(bytes(c) for c in palette)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0))
            + chunk(b"PLTE", plte)
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def record_strip_png(strip: RecordStrip) -> bytes:
    """The strip as PNG bytes. Deterministic: the same strip always gives the same bytes."""
    img, palette = strip_index_image(strip)
    return _palette_png(img, palette)


def _hex(rgb) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def record_strip_html(strip: RecordStrip, *, title: str = "", link_particle=None) -> str:
    """An HTML fragment: the PNG inline, a legend with counts, and the particle table.

    ``link_particle`` (``index -> href``) makes each particle row a link; the triage server passes
    its own particle page, a file written by the CLI passes nothing.
    """
    import base64

    img, palette = strip_index_image(strip)
    png = _palette_png(img, palette)
    counts = {c: 0 for c in strip.categories}
    for p in strip.particles:
        counts[p.category(strip.colour_by)] += 1
    legend = "".join(
        f"<span style='display:inline-block;margin-right:1em'>"
        f"<span style='display:inline-block;width:.9em;height:.9em;vertical-align:middle;"
        f"background:{_hex(palette[_FIRST_CATEGORY + k])};border:1px solid #888'></span> "
        f"{html.escape(c)} ({counts[c]})</span>"
        for k, c in enumerate(strip.categories))
    roles = (f"<span style='color:{_hex(_ROLE_COLOURS[_BOUNDARY])}'>&#9632;</span> boundary slice"
             f" &middot; <span style='color:{_hex(_ROLE_COLOURS[_UNCLAIMED])}'>&#9632;</span> "
             f"shadow in no particle window &middot; <span style='color:"
             f"{_hex(_ROLE_COLOURS[_TICK])}'>&#9632;</span> every fifth particle")
    rows = []
    for n, p in enumerate(strip.particles, start=1):
        label = str(p.index)
        if link_particle is not None:
            label = f"<a href='{html.escape(link_particle(p.index))}'>{p.index}</a>"
        rows.append(f"<tr><td>{n}{' *' if n % 5 == 0 else ''}</td><td>{label}</td>"
                    f"<td>{p.record}</td><td>{p.first_slice}-{p.last_slice}</td>"
                    f"<td>{html.escape(p.reject or '?')}</td>"
                    f"<td>{html.escape(p.habit or '?')}</td></tr>")
    first, last = strip.records[0], strip.records[-1]
    n_boundary = int(strip.boundary.sum())
    return (
        (f"<h2>{html.escape(title)}</h2>" if title else "")
        + f"<p class='muted'>records {first}-{last}, one band each (1700 slices across, one row "
        f"per diode); {len(strip.particles)} particle(s); {n_boundary} boundary slice(s); "
        f"coloured by {html.escape(strip.colour_by)}</p>"
        + f"<img alt='record strip' style='width:100%;image-rendering:pixelated' "
        f"src='data:image/png;base64,{base64.b64encode(png).decode()}'>"
        + f"<p>{legend}</p><p class='muted'>{roles}</p>"
        + "<table><tr><th>#</th><th>proc row</th><th>record</th><th>slices</th>"
        "<th>reject</th><th>habit</th></tr>" + "".join(rows) + "</table>")


# ---------------------------------------------------------------------------------------------
# The one-second comparison
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SecondComparison:
    """One second of two size-distribution files, bin by bin.

    ``ours``/``theirs`` are the named variable's per-bin values at that second, read from each
    file unscaled. ``differing`` marks the bins where they are not equal within ``rtol`` (exact
    by default; NaN equals NaN). ``particles`` are the proc rows of that second whose
    ``diameter_var`` falls in a differing bin, ``[bin_min, bin_max)`` -- a guide to where to look,
    not the binning itself: ``count`` additionally requires the particle's codes, centre-in flag
    and time window to pass,
    which is why each listed particle carries its reject code and centre-in flag.
    """

    second: int
    variable: str
    bin_min: np.ndarray
    bin_max: np.ndarray
    ours: np.ndarray
    theirs: np.ndarray
    differing: np.ndarray
    rtol: float
    diameter_var: str | None = None
    particles: tuple[dict, ...] = ()

    @property
    def n_differing(self) -> int:
        """How many bins differ at this second."""
        return int(self.differing.sum())

    def summary(self) -> str:
        """Plain text: the differing bins with both values, then the particles behind them."""
        lines =[f"second {self.second:06d}, variable {self.variable!r}: "
                 f"{self.n_differing} of {self.differing.size} bin(s) differ"
                 f" ({'exact' if self.rtol == 0 else f'rtol {self.rtol:g}'})"]
        for i in np.nonzero(self.differing)[0]:
            lines.append(f"  bin {i + 1:3d} [{self.bin_min[i]:.4g}, {self.bin_max[i]:.4g}): "
                         f"ours {self.ours[i]:.6g}  theirs {self.theirs[i]:.6g}  "
                         f"diff {self.ours[i] - self.theirs[i]:+.6g}")
        if self.diameter_var is not None:
            lines.append(f"  {len(self.particles)} particle(s) of this second fall in a "
                         f"differing bin by {self.diameter_var}")
            for p in self.particles:
                lines.append(f"    proc row {p['index']}: bin {p['bin']}, "
                             f"{self.diameter_var} {p['diameter']:.4g}, reject "
                             f"{p['reject'] or '?'}, centre-in {p['center_in']}")
        return "\n".join(lines)


def _sd_second(ds, second: int, variable: str, label: str):
    times = np.asarray(ds.variables["time"][:]).reshape(-1).astype(float)
    hits = np.nonzero(np.floor(times) == second)[0]
    if hits.size == 0:
        near = times[np.argsort(np.abs(times - second))[:3]]
        raise KeyError(f"{label} has no second {second:06d}; nearest "
                       f"{', '.join(f'{int(t):06d}' for t in near)}")
    if variable not in ds.variables:
        raise KeyError(f"{label} has no variable {variable!r}")
    var = ds.variables[variable]
    if var.dimensions[0] != ds.variables["time"].dimensions[0] or var.ndim != 2:
        raise ValueError(f"{variable!r} is not a (time, bin) variable in {label}")
    return np.asarray(var[hits[0], :], dtype=float).reshape(-1)


def compare_second(ours_sd, theirs_sd, second: int, *, variable: str = "count",
                   proc=None, diameter_var: str = "image_diam_minR",
                   rtol: float = 0.0) -> SecondComparison:
    """Compare one second (``HHMMSS``) of two ``sd`` files; list the particles behind the cells.

    ``ours_sd``/``theirs_sd`` and ``proc`` are paths. ``proc``, when given, is the per-particle
    file behind ``ours_sd``; without it no particles are listed. The two files must share a bin
    ladder, or the comparison raises rather than setting two different bins side by side.
    ``diameter_var`` is stated in every rendering because the ``sd`` file does not record which
    size definition its run chose -- the ``.call`` sidecar does.
    """
    import netCDF4

    with netCDF4.Dataset(str(ours_sd)) as a, netCDF4.Dataset(str(theirs_sd)) as b:
        a.set_auto_maskandscale(False)
        b.set_auto_maskandscale(False)
        bin_min = np.asarray(a.variables["bin_min"][:], dtype=float)
        bin_max = np.asarray(a.variables["bin_max"][:], dtype=float)
        if not (np.array_equal(bin_min, np.asarray(b.variables["bin_min"][:], dtype=float))
                and np.array_equal(bin_max, np.asarray(b.variables["bin_max"][:], dtype=float))):
            raise ValueError("the two files have different bin ladders; compare them "
                             "with `arrayprobe compare` rather than bin by bin")
        ours = _sd_second(a, second, variable, str(ours_sd))
        theirs = _sd_second(b, second, variable, str(theirs_sd))
    equal = np.isclose(ours, theirs, rtol=rtol, atol=0.0, equal_nan=True)
    differing = ~equal

    particles: tuple[dict, ...] = ()
    if proc is not None:
        with netCDF4.Dataset(str(proc)) as p:
            p.set_auto_maskandscale(False)
            t = np.asarray(p.variables["Time"][:]).reshape(-1).astype(float)
            d = np.asarray(p.variables[diameter_var][:]).reshape(-1).astype(float)
            rej = (np.asarray(p.variables["image_auto_reject"][:]).reshape(-1)
                   if "image_auto_reject" in p.variables else None)
            cin = (np.asarray(p.variables["image_center_in"][:]).reshape(-1)
                   if "image_center_in" in p.variables else None)
        rows = []
        for i in np.nonzero(np.floor(t) == second)[0]:
            inside = np.nonzero((bin_min <= d[i]) & (d[i] < bin_max))[0]
            if inside.size and differing[inside[0]]:
                rows.append({
                    "index": int(i), "bin": int(inside[0]) + 1, "diameter": float(d[i]),
                    "reject": _char(rej[i], _REJECT_BY_VALUE) if rej is not None else None,
                    "center_in": int(cin[i]) if cin is not None else None,
                })
        particles = tuple(rows)
    return SecondComparison(second, variable, bin_min, bin_max, ours, theirs, differing,
                            rtol, diameter_var if proc is not None else None, particles)


def second_comparison_html(cmp: SecondComparison, *, ours_label: str = "ours",
                           theirs_label: str = "theirs") -> str:
    """An HTML fragment: every bin where either file is non-zero, differing rows marked."""
    shown = np.nonzero(cmp.differing | (np.nan_to_num(cmp.ours) != 0)
                       | (np.nan_to_num(cmp.theirs) != 0))[0]
    rows = []
    for i in shown:
        mark = " style='background:#fde2e2'" if cmp.differing[i] else ""
        rows.append(f"<tr{mark}><td>{i + 1}</td><td>{cmp.bin_min[i]:.4g}</td>"
                    f"<td>{cmp.bin_max[i]:.4g}</td><td>{cmp.ours[i]:.6g}</td>"
                    f"<td>{cmp.theirs[i]:.6g}</td>"
                    f"<td>{cmp.ours[i] - cmp.theirs[i]:+.6g}</td>"
                    f"<td>{'differs' if cmp.differing[i] else ''}</td></tr>")
    head = (f"<h2>Second {cmp.second:06d}: {html.escape(cmp.variable)}</h2>"
            f"<p>{cmp.n_differing} of {cmp.differing.size} bin(s) differ "
            f"({'exact comparison' if cmp.rtol == 0 else f'rtol {cmp.rtol:g}'}); "
            f"{len(shown)} bin(s) shown -- every bin where either file is non-zero or the two "
            f"differ</p>")
    table = (f"<table><tr><th>bin</th><th>min</th><th>max</th><th>{html.escape(ours_label)}"
             f"</th><th>{html.escape(theirs_label)}</th><th>diff</th><th></th></tr>"
             + "".join(rows) + "</table>")
    if cmp.diameter_var is None:
        parts = "<p class='muted'>no proc file given, so no particles are listed</p>"
    else:
        prow = "".join(
            f"<tr><td>{p['index']}</td><td>{p['bin']}</td><td>{p['diameter']:.4g}</td>"
            f"<td>{html.escape(p['reject'] or '?')}</td><td>{p['center_in']}</td></tr>"
            for p in cmp.particles)
        parts = (f"<h3>Particles of this second in a differing bin</h3>"
                 f"<p class='muted'>by <code>{html.escape(cmp.diameter_var)}</code>, "
                 f"[bin_min, bin_max). The sd file does not record which size definition its "
                 f"run binned by (its <code>.call</code> sidecar does), and <code>count</code> "
                 f"also requires the reject codes, centre-in and time window to pass -- so "
                 f"this list is where to look, not what was counted.</p>"
                 f"<table><tr><th>proc row</th><th>bin</th><th>diameter</th><th>reject</th>"
                 f"<th>centre-in</th></tr>{prow}</table>")
    return head + table + parts


def per_second_counts(hhmmss) -> tuple[np.ndarray, np.ndarray]:
    """Particles per second from a proc file's ``Time`` (``HHMMSS``): ``(seconds, counts)``.

    ``seconds`` are seconds of day, floored; non-finite times are dropped. The counts sum to the
    number of finite particle times -- the triage server's rate panel draws exactly this.
    """
    from arrayprobe_uiops.sizedist_core import _hhmmss_to_insec

    insec = np.floor(_hhmmss_to_insec(np.asarray(hhmmss, dtype=float).reshape(-1)))
    finite = insec[np.isfinite(insec)]
    seconds, counts = np.unique(finite, return_counts=True)
    return seconds, counts


# ---------------------------------------------------------------------------------------------
# How much of a between-engine difference hollow ('H') particles can make.
#
# UIOOPS v3.5 divides a hollow ('H', Poisson-spot) particle's `image_diam_minR` by its Korolev
# `size_factor` (1.07-1.9; `arrayprobe_uiops/measure.py:318-319`) before sizeDist bins it. SODA-2
# bins the uncorrected circle unless `apply_psc` is set. So wherever 'H' particles are common,
# the two engines put the same particles in different bins. `hollow_share` reads ONE v3.5 proc
# file and says, per size bin, how many particles that division moves, in which direction. It
# reads the file and writes nothing: no product changes.

#: Codes the v3.5 product counts in `image_auto_reject` (accepted, 'H' hollow, 'h', 'u', 'R'),
#: the same set the 'H'-undivided side of the ARM three-way comparison counts.
HOLLOW_ACCEPTED_CODES = "0HhuR"

#: The verdict fires when the division changes the range's accepted count by at least this
#: fraction of the count as written AND by more than twice that count's Poisson standard error.
#: 5 % is the counting noise of a range holding 400 particles (1/sqrt(400)); the two measured
#: cases where hollow sizing drove a between-engine difference sit far above it (ARM 2D-S,
#: 55-115 um: 07-07 a 75 % shift, 07-08 a 24 % shift), and the Poisson clause keeps a sparse
#: range from firing on a handful of particles.
HOLLOW_VERDICT_MIN_FRACTION = 0.05


@dataclass
class HollowShare:
    """Per-bin hollow census of one v3.5 proc file. Every array has one entry per bin.

    ``moved_out[b]``: accepted 'H' particles whose undivided size is in bin ``b`` and whose
    written (divided) size is not -- the correction takes them out of ``b``.
    ``moved_in[b]``: accepted 'H' particles whose written size is in ``b`` and whose undivided
    size is not -- the correction brings them into ``b``.
    So ``accepted = accepted_undivided - moved_out + moved_in`` in every bin.
    """

    edges_um: np.ndarray
    accepted: np.ndarray            # accepted particles at their written sizes
    accepted_h: np.ndarray          # of which 'H'
    moved_out: np.ndarray
    moved_in: np.ndarray
    accepted_undivided: np.ndarray  # the same particles with each 'H' at size x size_factor
    min_fraction: float = HOLLOW_VERDICT_MIN_FRACTION
    source: str = ""

    @property
    def h_share(self) -> np.ndarray:
        """Accepted 'H' / accepted, per bin (NaN in an empty bin)."""
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(self.accepted > 0, self.accepted_h / self.accepted, np.nan)

    @property
    def ratio_undivided_to_written(self) -> np.ndarray:
        """Count without the correction / count with it, per bin: what an engine that does not
        divide (SODA-2 with ``apply_psc = 0``) would count against what v3.5 counts, from the
        sizing alone."""
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(self.accepted > 0, self.accepted_undivided / self.accepted, np.nan)

    @property
    def net_shift(self) -> int:
        """Change in the range's accepted count caused by the division (written - undivided)."""
        return int(self.accepted.sum() - self.accepted_undivided.sum())

    @property
    def fires(self) -> bool:
        """The verdict rule: see :data:`HOLLOW_VERDICT_MIN_FRACTION`."""
        n = max(int(self.accepted.sum()), 1)
        shift = abs(self.net_shift)
        return shift > 0 and shift >= self.min_fraction * n and shift > 2.0 * np.sqrt(n)

    def verdict(self) -> str:
        """One line, ``YES: ...`` when :attr:`fires` and ``NO: ...`` otherwise: the range, the
        count undivided and as written, the fractional shift and the rule applied. Computes
        nothing beyond the census."""
        lo, hi = self.edges_um[0], self.edges_um[-1]
        n, nu = int(self.accepted.sum()), int(self.accepted_undivided.sum())
        frac = self.net_shift / n if n else float("nan")
        rule = f"rule: |shift| >= {self.min_fraction:.0%} of the count and > 2 sqrt(count)"
        if self.fires:
            return (f"YES: hollow sizing can explain a between-engine difference in "
                    f"{lo:g}-{hi:g} um: the 'H' division changes the accepted count from "
                    f"{nu} (undivided) to {n} (as written), {frac:+.1%} ({rule}).")
        return (f"NO: hollow sizing moves too little to explain a between-engine difference in "
                f"{lo:g}-{hi:g} um: {nu} undivided against {n} as written, {frac:+.1%} ({rule}).")


def _codes(var) -> np.ndarray:
    raw = np.asarray(var[:])
    if raw.dtype.kind in "SU":
        flat = raw.astype("S1").reshape(-1)
        return np.array([c[0] if len(c) else -1 for c in flat], dtype=np.int64)
    return np.ma.filled(np.ma.asarray(raw), -1).astype(np.int64).reshape(-1)


def hollow_share(proc_path, bin_edges_um, *,
                 min_fraction: float = HOLLOW_VERDICT_MIN_FRACTION) -> HollowShare:
    """Per-bin hollow census of one v3.5 proc file (see :class:`HollowShare`).

    ``bin_edges_um`` are ascending edges in micrometres; a bin is ``[lo, hi)``, sizeDist's
    ``bin_index`` rule. Accepted means ``image_auto_reject`` in :data:`HOLLOW_ACCEPTED_CODES`
    with ``image_center_in == 1``. The written size is ``image_diam_minR`` (mm) and the undivided
    size of an 'H' particle is ``image_diam_minR * size_factor``, the rebin
    ``compare_ena_threeway.py --uiops-h-undivided`` uses. sizeDist's own reject stage (area
    ratio, interarrival) is not applied, so the counts are the proc file's accepted particles,
    not the product's ``Counts``. Reads the file; writes nothing.
    """
    import netCDF4

    edges = np.asarray(bin_edges_um, dtype=np.float64).reshape(-1)
    if edges.size < 2 or np.any(np.diff(edges) <= 0):
        raise ValueError("bin_edges_um must be at least two strictly ascending edges")
    with netCDF4.Dataset(str(proc_path)) as d:
        for name in ("image_auto_reject", "image_center_in", "image_diam_minR", "size_factor"):
            if name not in d.variables:
                raise ValueError(f"{proc_path}: no {name!r}; hollow_share reads a UIOPS v3.5 "
                                 "proc file")
        code = _codes(d.variables["image_auto_reject"])
        cin = np.ma.filled(np.ma.asarray(d.variables["image_center_in"][:]), -1).reshape(-1)
        diam = np.ma.filled(np.ma.asarray(d.variables["image_diam_minR"][:],
                                          dtype=np.float64), np.nan).reshape(-1)
        sf = np.ma.filled(np.ma.asarray(d.variables["size_factor"][:], dtype=np.float64),
                          np.nan).reshape(-1)
    accepted = np.isin(code, [ord(c) for c in HOLLOW_ACCEPTED_CODES]) & (cin == 1)
    is_h = accepted & (code == ord("H"))
    written_um = diam * 1000.0
    undiv_um = np.where(is_h, diam * sf, diam) * 1000.0
    nb = edges.size - 1

    def bin_of(x: np.ndarray) -> np.ndarray:
        b = np.searchsorted(edges, x, side="right") - 1
        b[~np.isfinite(x) | (x < edges[0]) | (x >= edges[-1])] = -1
        return b

    bw, bu = bin_of(written_um), bin_of(undiv_um)

    def count(mask: np.ndarray, b: np.ndarray) -> np.ndarray:
        sel = mask & (b >= 0)
        return np.bincount(b[sel], minlength=nb)[:nb].astype(np.int64)

    moved = is_h & (bw != bu)
    return HollowShare(
        edges_um=edges,
        accepted=count(accepted, bw),
        accepted_h=count(is_h, bw),
        moved_out=count(moved, bu),
        moved_in=count(moved, bw),
        accepted_undivided=count(accepted, bu),
        min_fraction=min_fraction,
        source=str(proc_path),
    )


def hollow_share_text(share: HollowShare) -> str:
    """The census as a plain-text table, one row per bin, ending with the verdict."""
    rows = [f"hollow ('H') census of {share.source}",
            f"{'bin (um)':>15} {'accepted':>9} {'H':>7} {'H share':>8} {'out':>6} {'in':>6} "
            f"{'undivided':>10} {'undiv/written':>14}"]
    share_h, ratio = share.h_share, share.ratio_undivided_to_written
    for b in range(share.accepted.size):
        span = f"{share.edges_um[b]:g}-{share.edges_um[b + 1]:g}"
        rows.append(f"{span:>15} {share.accepted[b]:>9d} {share.accepted_h[b]:>7d} "
                    f"{share_h[b]:>8.3f} {share.moved_out[b]:>6d} {share.moved_in[b]:>6d} "
                    f"{share.accepted_undivided[b]:>10d} {ratio[b]:>14.3f}")
    rows.append("out: 'H' the correction moves out of the bin; in: 'H' it moves into the bin; "
                "undivided = accepted - in + out")
    rows.append(share.verdict())
    return "\n".join(rows)


def hollow_share_at_or_above(proc_path, threshold_um: float) -> dict:
    """Hollow summary of one v3.5 proc file at or above one size: :func:`hollow_share` over the
    open range ``[threshold_um, inf)``, as a dict.

    ``accepted`` and ``accepted_h`` count accepted particles (and the 'H' among them) whose
    written size is at or above the threshold; ``h_share`` is their ratio; ``accepted_undivided``
    counts with each 'H' at ``size x size_factor``; ``ratio_undivided_to_written`` is
    ``accepted_undivided / accepted``, the factor by which an engine that does not divide (SODA-2
    with ``apply_psc = 0``) would count more above the threshold from sizing alone. Divide a
    measured between-engine N ratio by it to see what hollow sizing leaves unexplained.
    """
    share = hollow_share(proc_path, [float(threshold_um), np.inf])
    n, nh = int(share.accepted[0]), int(share.accepted_h[0])
    nu = int(share.accepted_undivided[0])
    return {
        "source": share.source, "threshold_um": float(threshold_um),
        "accepted": n, "accepted_h": nh, "h_share": nh / n if n else float("nan"),
        "accepted_undivided": nu,
        "ratio_undivided_to_written": nu / n if n else float("nan"),
        "verdict": share.verdict(),
    }
