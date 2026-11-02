# SPDX-License-Identifier: BSD-3-Clause
"""Track V -- particle visualisation. Not a port stage: new capability UIOOPS
does not have, built on files the S2-S4 chain already produces.

**The one dependency, already satisfied by S3.** A proc file records
``parent_rec_num`` and ``position`` for every particle: which image record it
came from, and the first/last slice (1-based, inclusive) within that record's
1700-slice block. Together with the record's raw ``data`` in the source image
file, those two reconstruct the exact ``c`` matrix ``imgproc_sm`` saw --
transcribed here from ``imgProc_sm.m:266-268`` (``ind_matrix = 65535 -
data(start:j-1,:)``, ``c = dec2bin_concat(...)``), not imported from
``imgproc.py``: the reconstruction is four lines, and duplicating it here
keeps this module from being able to perturb S3's own validated code path by
accident. See the plan's "Enhancement track V" section for the open scope
questions this was built against.

Convention throughout: ``c`` is a ``(n_slices, n_diodes)`` boolean array,
``True`` where a diode was **shadowed** (the particle silhouette) -- matching
``c == '0'`` at every UIOOPS call site (``imgProc_sm.m:63`` and the CGAL_minR
shim's own note), just as a boolean rather than a char array.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .matlab_compat import HOLROYD_HABITS, REJECT_CODES, dec2bin_concat

__all__ = [
    "DRAWABLE_PROBES",
    "reconstruct_particle_image",
    "particle_info",
    "crop_to_content",
    "render_particle",
    "render_contact_sheet",
    "render_gallery_html",
    "particle_thumbnail_png",
    "unverified_placeholder_png",
    "grid_shape",
    "wrap_title",
    "record_slice_um",
    "particle_grid",
]

_HABIT_BY_CODE = {v: k for k, v in HOLROYD_HABITS.items()}
_REJECT_BY_CODE = {v: k for k, v in REJECT_CODES.items()}


#: Probes whose framing this module draws. 2DC/2DP stay refused by name even
#: though ``reconstruct_particle_image`` now applies ``image_slice_offset``
#: (2026-09-20 fix; their offset is 1, ``data(start+1:j-1,:)``, ``:555``): the
#: only oracle checked is ``tests/data/s7c_2dc_octave_golden.nc``, a two-
#: particle hand-built synthetic file, which settles that the *row selection*
#: now matches ``SliceCount`` exactly (it does not store the pixel content of
#: ``c`` itself, only per-particle stats), and says nothing about a real 2DC/
#: 2DP campaign file. That gap, not the offset arithmetic, is why the
#: exclusion stays -- see ``test_render.py::TestReconstructOffset`` for the
#: golden comparison this rests on.
DRAWABLE_PROBES = ("2DS", "HVPS", "CIP", "PIP", "Fast2DC")


def reconstruct_particle_image(image_ds, proc_ds, particle_index: int, *,
                               probe: str = "2DS") -> np.ndarray:
    """The boolean ``(n_slices, n_diodes)`` silhouette for one particle.

    ``image_ds``/``proc_ds`` are open ``netCDF4.Dataset`` handles for the
    image file and ``proc.*.nc`` (the *same* flight -- nothing here
    checks that they match, since the caller already has both open and a
    mismatch would show up immediately as garbage).

    ``particle_index`` is 0-based into the proc file's particle axis, i.e.
    the row index the rest of the proc file's per-particle variables use
    directly (``image_width[particle_index]`` etc.).

    ``probe`` selects the framing ``imgproc`` uses for that probe, read from
    :data:`arrayprobe.constants.IMGPROC_CONFIG` rather than restated: 2D-S and
    HVPS invert 16-bit words (``65535 - data``, ``:562``); CIP/PIP/Fast2DC use
    8-bit words as stored (``:556,:559``). The default is the 2D-S framing, so
    a call without ``probe`` draws a 2D-S image; a CIP image needs
    ``probe="CIP"``, or it comes back as an inverted 128-column picture.
    """
    from .constants import IMGPROC_CONFIG

    if probe not in DRAWABLE_PROBES:
        raise ValueError(f"probe {probe!r} is not drawable here; drawable: {DRAWABLE_PROBES}")
    cfg = IMGPROC_CONFIG[probe]
    parent_rec = int(proc_ds.variables["parent_rec_num"][particle_index])  # 1-based
    start, end = (int(v) for v in proc_ds.variables["position"][particle_index])
    block = image_ds.variables["data"][parent_rec - 1, :, :]  # (1700, n_words)
    # imgproc.py:893's slice_start -- the proc file's stored ``start`` is the
    # raw pre-offset value (``images.position(kk,:) = [start, j-1]``,
    # imgProc_sm.m:575), so the read side must add the same
    # ``cfg.image_slice_offset`` the write side added, or a probe with a
    # nonzero offset (2DC/2DP: 1, imgProc_sm.m:555) gains one extra row at the
    # front -- a header/timing slice imgProc_sm.m never put in the particle.
    # For 2D-S/HVPS (offset 0) this is exactly the prior ``start - 1`` and
    # changes nothing (test_render.py::TestOffsetIsNoopFor2DS).
    slice_start = start - 1 + cfg.image_slice_offset
    data_slice = np.asarray(block[slice_start:end, :])  # :266's data(start:j-1,:)
    # :266 / :562, inverted so '1' bits are lit (2D-S, HVPS); :556,:559 as stored.
    ind_matrix = 65535 - data_slice if cfg.image_invert else data_slice
    c = dec2bin_concat(ind_matrix, cfg.image_word_bits)  # :267-268, '0'/'1' per bit
    return c == ord("0")  # '0' == shadowed, per the module docstring


def particle_info(proc_ds, particle_index: int) -> dict:
    """The per-particle scalars worth showing alongside the image."""
    def get(name, default=None):
        """One per-particle scalar as a float, or ``default`` if the file has no
        such variable.

        Absence is normal rather than exceptional here: a proc file's variable
        set depends on the probe type and on ``iRectEllipse``, so a display
        helper that raised on a missing name would fail on perfectly good
        files. This is a viewer, and it never feeds a computed number.
        """
        return (float(proc_ds.variables[name][particle_index])
                if name in proc_ds.variables else default)

    reject_code = get("image_auto_reject")
    habit_code = get("holroyd_habit")
    return {
        "particle_index": particle_index,
        "parent_rec_num": int(get("parent_rec_num")),
        "particle_num": int(get("particle_num")),
        "image_width": get("image_width"),
        "image_length": get("image_length"),
        "reject_code": _REJECT_BY_CODE.get(int(reject_code)) if reject_code else None,
        "habit_code": _HABIT_BY_CODE.get(int(habit_code)) if habit_code else None,
        "diam_minR": get("image_diam_minR"),
    }


def _label(info: dict) -> str:
    reject = info["reject_code"] or "?"
    habit = info["habit_code"] or "?"
    diam = info["diam_minR"]
    diam_s = f"{diam:.3f}mm" if diam is not None and np.isfinite(diam) else "n/a"
    return (f"rec {info['parent_rec_num']} #{info['particle_num']}  "
            f"reject={reject!r} habit={habit!r} diam={diam_s}")


def crop_to_content(c: np.ndarray, pad: int = 3) -> np.ndarray:
    """``c`` (or its shadowed bounding box plus ``pad`` slices/diodes of
    margin on each side), for **display only**.

    ``reconstruct_particle_image`` is deliberately faithful to what
    ``imgProc_sm.m:266-268`` actually builds: the full slice window between
    consecutive boundary markers, which for a particle immediately after a
    fresh record (``position`` resets to 1) or after an unusually large gap
    can run hundreds of slices while the particle's own shadow -- what
    ``image_width``/``image_length`` measure -- occupies a handful of them
    near one end. At full scale that renders correctly; shrunk into a
    thumbnail, the shadow can fall below a pixel and the particle looks
    blank, which is misleading for visual verification even though nothing
    about the reconstruction or the accept/reject decision is wrong.

    Cropping is presentation only: it never touches ``reconstruct_particle_image``
    or any value read from the proc file, and every rejected pixel outside the
    returned window was never anything but background in the full array either.
    An all-lit (no shadowed pixel) input is returned unchanged, since there is
    no content to crop to.
    """
    rows = np.any(c, axis=1)
    cols = np.any(c, axis=0)
    if not rows.any():
        return c
    # ``int(...)`` around every ``argmax``: these four are only ever used as slice
    # bounds, and mixing ``np.intp`` with the plain ``0`` / ``c.shape[n] - 1``
    # literals below is what mypy objects to.  Slicing is identical either way --
    # this is a presentation-only crop, so no computed number depends on it.
    r0, r1 = int(np.argmax(rows)), len(rows) - 1 - int(np.argmax(rows[::-1]))
    c0, c1 = int(np.argmax(cols)), len(cols) - 1 - int(np.argmax(cols[::-1]))
    r0 = max(0, r0 - pad)
    r1 = min(c.shape[0] - 1, r1 + pad)
    c0 = max(0, c0 - pad)
    c1 = min(c.shape[1] - 1, c1 + pad)
    return c[r0:r1 + 1, c0:c1 + 1]


def render_particle(image_ds, proc_ds, particle_index: int, ax=None, *, crop: bool = False):
    """One particle's silhouette on a matplotlib Axes, labeled with its reject
    code, habit, and min-enclosing-circle diameter. Returns the Figure (a
    fresh one if ``ax`` is None) -- so this is equally usable from a CLI
    (save the Figure), a notebook (let it auto-display), or assembled into a
    contact sheet / HTML gallery (pass an existing ``ax``).

    ``crop`` (default off, so single-particle/CLI use is unaffected): display
    only the shadow's own bounding box plus a small margin, via
    :func:`crop_to_content`, for the thumbnail-legibility reason documented
    there. Off by default because the full window is sometimes exactly what a
    reader wants (e.g. to see how much of a record a particle actually used).
    """
    import matplotlib.pyplot as plt

    c = reconstruct_particle_image(image_ds, proc_ds, particle_index)
    if crop:
        c = crop_to_content(c)
    info = particle_info(proc_ds, particle_index)

    owns_fig = ax is None
    if owns_fig:
        fig, ax = plt.subplots(figsize=(max(2.0, c.shape[1] / 20), max(1.2, c.shape[0] / 20)))
    else:
        fig = ax.figure

    ax.imshow(c, cmap="Greys", aspect="auto", interpolation="nearest")
    ax.set_title(_label(info), fontsize=8)
    ax.set_xlabel("diode", fontsize=7)
    ax.set_ylabel("slice", fontsize=7)
    ax.tick_params(labelsize=6)
    if owns_fig:
        fig.tight_layout()
    return fig


def render_contact_sheet(image_ds, proc_ds, particle_indices, ncols: int = 5,
                         *, crop: bool = False):
    """A grid of several particles' silhouettes, one Axes each -- the broader
    eyeballed sanity check the plan names as track V's second rendering mode.

    ``crop``: see :func:`render_particle` -- worth turning on here specifically,
    since a contact sheet's whole point is many particles at thumbnail scale,
    where an uncropped large-window particle is the most likely to look blank.
    """
    import matplotlib.pyplot as plt

    particle_indices = list(particle_indices)
    n = len(particle_indices)
    ncols = max(1, min(ncols, n))
    nrows = -(-n // ncols)  # ceil
    fig, axes = plt.subplots(nrows, ncols, figsize=(3.2 * ncols, 2.4 * nrows), squeeze=False)
    for k, idx in enumerate(particle_indices):
        ax = axes[k // ncols][k % ncols]
        render_particle(image_ds, proc_ds, idx, ax=ax, crop=crop)
    for k in range(n, nrows * ncols):
        axes[k // ncols][k % ncols].axis("off")
    fig.tight_layout()
    return fig


# ---- Review figures: particles in a readable grid --------------------------------------------
# The author, 2026-10-03: "Make them properly in not horizontal one row, but bigger rows so I can
# actually see the images" and "grids must be vertical, 2x2 or 3x3 panels, so the page is neither
# too wide nor too long". Every particle figure made for review goes through ``particle_grid``.
# Presentation only: nothing here reads or changes a computed number.

#: Most columns a review grid uses; a 3 x 3 grid of 3.2-inch panels fits one screen or page.
GRID_MAX_COLS = 3


def grid_shape(n: int, max_cols: int = GRID_MAX_COLS) -> tuple[int, int]:
    """``(rows, cols)`` for ``n`` panels: 1 x 1 for one, two columns up to four (2 x 2), three
    columns beyond. Never one row of more than two panels, so particles stay large."""
    if n <= 0:
        return (0, 0)
    ncols = 1 if n == 1 else (2 if n <= 4 else max_cols)
    ncols = min(ncols, max_cols)
    return (-(-n // ncols), ncols)


def wrap_title(text: str, width: int) -> str:
    """``text`` with every line wrapped to at most ``width`` characters, keeping the caller's own
    line breaks, so a panel title never runs past its panel."""
    import textwrap

    out: list[str] = []
    for line in str(text).split("\n"):
        out.extend(textwrap.wrap(line, width=max(8, width), break_long_words=True) or [""])
    return "\n".join(out)


def record_slice_um(image_ds, proc_ds, particle_index: int, diode_um: float) -> float | None:
    """Along-track length of one slice, in micrometres, for the record a particle came from:
    ``diode_um / tasRatio``, the convention v3.5's own shape statistics use
    (``holroyd_new.m`` via ``arrayprobe_uiops.habit.calc_stat_new``: ``tx = i / tas_ratio``).
    ``None`` when the image file has no usable ``tasRatio`` for that record, so the caller draws
    the slice as one diode and says the aspect is not true."""
    if "tasRatio" not in image_ds.variables:
        return None
    rec = int(proc_ds.variables["parent_rec_num"][particle_index])  # 1-based
    try:
        r = float(np.ma.filled(image_ds.variables["tasRatio"][rec - 1], np.nan))
    except (IndexError, ValueError, TypeError):
        return None
    if not np.isfinite(r) or r <= 0:
        return None
    return diode_um / r


def _nice_bar_um(span_um: float) -> float:
    """A round scale-bar length no longer than about 40 % of ``span_um``."""
    steps = (10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000)
    fits = [v for v in steps if v <= span_um * 0.4]
    return float(fits[-1] if fits else steps[0])


def particle_grid(images, titles=None, *, diode_um: float = 10.0, slice_um=None,
                  title_colors=None, suptitle: str | None = None, panel_in: float = 3.2,
                  fontsize: float = 10.0, crop_pad: int = 3, max_cols: int = GRID_MAX_COLS,
                  ring_small: int = 0):
    """A review figure: one large panel per particle in a grid (:func:`grid_shape`), each image
    cropped to its shadowed pixels plus ``crop_pad`` (:func:`crop_to_content`), drawn with
    nearest-neighbour pixels, a scale bar in micrometres and a wrapped title of ``fontsize`` pt.

    ``images``: boolean ``(n_slices, n_diodes)`` arrays, as :func:`reconstruct_particle_image`
    returns. ``slice_um``: the along-track length of one slice, a scalar or one value per image
    (see :func:`record_slice_um`); where it is ``None`` a slice is drawn one diode long and the
    panel title says "aspect not true". ``ring_small``: circle every 8-connected group of at
    most this many pixels, so a single shadowed pixel stays visible at page scale (0: none).
    Returns the Figure.
    """
    import matplotlib.pyplot as plt

    images = [np.asarray(c) > 0 for c in images]
    n = len(images)
    titles = list(titles) if titles is not None else [""] * n
    colors = list(title_colors) if title_colors is not None else ["black"] * n
    slices: list[Any]  # slice lengths in um, or None per panel
    if slice_um is None or np.isscalar(slice_um):
        slices = [slice_um] * n
    else:
        slices = list(slice_um)
    nrows, ncols = grid_shape(n, max_cols)
    nrows, ncols = max(nrows, 1), max(ncols, 1)
    chars = int(panel_in * 72 / (fontsize * 0.58))
    wrapped = []
    for k in range(n):
        s = slices[k]
        note = (f"slice {s:.1f} um (true aspect)" if s is not None
                else "aspect not true: slice drawn 1 diode long")
        wrapped.append(wrap_title(f"{titles[k]}\n{note}" if titles[k] else note, chars))
    lines = max([t.count("\n") + 1 for t in wrapped] or [1])
    title_in = lines * fontsize * 1.35 / 72
    head_in = 0.0
    if suptitle:
        suptitle = wrap_title(suptitle, int(ncols * panel_in * 72 / ((fontsize + 1) * 0.55)))
        head_in = (suptitle.count("\n") + 1) * (fontsize + 1) * 1.4 / 72 + 0.2
    fig, axes = plt.subplots(nrows, ncols, squeeze=False, layout="constrained",
                             figsize=(ncols * panel_in + 0.3,
                                      nrows * (panel_in + title_in + 0.15) + head_in))
    for ax in axes.flat:
        ax.set_axis_off()
    for k, c in enumerate(images):
        ax = axes[k // ncols][k % ncols]
        ax.set_axis_on()
        sub = crop_to_content(c, pad=crop_pad) if c.any() else c
        s = slices[k] if slices[k] is not None else diode_um
        h_um, w_um = sub.shape[0] * s, sub.shape[1] * diode_um
        span = max(h_um, w_um)
        bar = _nice_bar_um(span)
        margin = 0.16 * span
        ax.imshow(sub, cmap="Greys", vmin=0, vmax=1, interpolation="nearest", aspect="equal",
                  extent=(0, w_um, h_um, 0))
        # Square view around the image so every panel is the same size; the bar sits below it.
        cx = w_um / 2
        half = (span + margin) / 2
        ax.set_xlim(cx - half, cx + half)
        ax.set_ylim(h_um + margin, h_um + margin - (span + margin))
        y = h_um + margin * 0.55
        x0 = cx - half + 0.05 * span
        ax.plot([x0, x0 + bar], [y, y], color="tab:blue", lw=3, solid_capstyle="butt")
        ax.text(x0 + bar / 2, y - margin * 0.12, f"{bar:g} um", ha="center", va="bottom",
                fontsize=fontsize - 1, color="tab:blue")
        if ring_small > 0 and sub.any():
            from scipy import ndimage

            lab, nlab = ndimage.label(sub, structure=np.ones((3, 3), dtype=int))
            # Boxes of the pieces too big to ring: a speck inside one (a hole's pixel) is not
            # ringed, only one standing apart.
            objs = ndimage.find_objects(lab)
            boxes = [objs[j - 1] for j in range(1, nlab + 1)
                     if (lab == j).sum() > ring_small]
            for j in range(1, nlab + 1):
                rr, cc = np.nonzero(lab == j)
                inside = any(b[0].start <= rr.mean() < b[0].stop
                             and b[1].start <= cc.mean() < b[1].stop for b in boxes)
                if rr.size <= ring_small and not inside:
                    ax.add_patch(plt.Circle(((cc.mean() + 0.5) * diode_um, (rr.mean() + 0.5) * s),
                                            radius=max(0.05 * span, 2 * diode_um), fill=False,
                                            color="tab:red", lw=1.5))
        ax.set_xticks([])
        ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_color("0.75")
        ax.set_title(wrapped[k], fontsize=fontsize, color=colors[k], loc="center")
    if suptitle:
        fig.suptitle(suptitle, fontsize=fontsize + 1)
    return fig


def render_gallery_html(image_ds, proc_ds, particle_indices, out_path, *,
                        title="Particle gallery", crop: bool = False):
    """A self-contained HTML page, one rendered particle per card, base64-
    embedded PNGs -- the third avenue named in the plan (published-artifact
    page), usable without a Python environment to view.

    ``crop``: see :func:`render_particle`.
    """
    import base64
    import io

    import matplotlib.pyplot as plt

    cards = []
    for idx in particle_indices:
        fig = render_particle(image_ds, proc_ds, idx, crop=crop)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150)
        plt.close(fig)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        info = particle_info(proc_ds, idx)
        cards.append(
            f'<div class="card"><img src="data:image/png;base64,{b64}" '
            f'alt="particle {idx}"><div class="cap">{_label(info)}</div></div>'
        )
    html = f"""<title>{title}</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #f7f8f9; color: #1d2329;
          margin: 1.5rem; }}
  h1 {{ font-size: 1.3rem; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
           gap: 1rem; }}
  .card {{ background: #fff; border: 1px solid #d9dee3; border-radius: 6px; padding: 0.6rem; }}
  .card img {{ width: 100%; height: auto; display: block; }}
  .cap {{ font-size: 0.72rem; color: #5c6672; margin-top: 0.4rem; font-family: monospace; }}
</style>
<h1>{title}</h1>
<div class="grid">
{"".join(cards)}
</div>
"""
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out_path


# --------------------------------------------------------------------------
# Whole-flight render to disk
#
# The other renderers in this module are viewers: they draw a handful of
# particles through matplotlib for a person to look at. This one writes an
# entire flight -- hundreds of thousands of particles -- into a directory tree,
# so matplotlib is the wrong tool twice over. It is slow per image, and it is
# not thread-safe (two crashes in the triage server showed
# that). These functions touch neither matplotlib nor netCDF
# concurrently, and write PNG bytes directly.
# --------------------------------------------------------------------------

#: How a particle is filed. ``accepted``/``rejected`` are UIOOPS's own verdict,
#: read from ``image_auto_reject``; ``unsure`` is a *human* verdict from the
#: triage sidecar and overrides both, because a person marking a particle
#: unsure is exactly what the word means here. A particle nobody has looked at
#: is never "unsure" -- it is filed by what the code decided.
PARTICLE_CLASSES = ("accepted", "rejected", "unsure")

#: ``image_auto_reject`` codes of an accepted particle: ``"0HhuR"``, the set sizeDist counts
#: (``sizeDist.m:1209``; v3.1.4 and v3.5 alike).  Hollow ``'H'``/``'h'`` particles are kept, sized
#: with/without the Korolev correction; the ORACLES production profile switches the hollow test
#: off, so no ``'H'``/``'h'`` occurs in its products and the set reduces to ``'0'`` there.  One
#: set serves both engines, so no stamp needs reading.
from arrayprobe_uiops.sizedist_core import GOOD_REJECT_CODES as _GOOD  # noqa: E402

ACCEPTED_CODES = np.array([ord(c) for c in _GOOD], dtype=np.int64)


def is_accepted_code(codes):
    """Boolean array (or scalar bool): which ``image_auto_reject`` codes are accepted."""
    return np.isin(np.asarray(codes), ACCEPTED_CODES)


def _png_bytes(mask: np.ndarray, scale: int = 1) -> bytes:
    """An 8-bit greyscale PNG of ``mask``: shadowed black, background white.

    Written with ``zlib`` and ``struct`` rather than a library because this is
    called once per particle for a whole flight, and because it keeps the
    whole-flight renderer free of any dependency the core package does not
    already have.
    """
    import struct
    import zlib

    img = np.where(np.asarray(mask, dtype=bool), 0, 255).astype(np.uint8)
    if scale > 1:
        img = np.repeat(np.repeat(img, scale, axis=0), scale, axis=1)
    height, width = img.shape
    # Each scanline is prefixed with a filter byte; 0 means "no filter".
    raw = b"".join(b"\x00" + img[row].tobytes() for row in range(height))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def particle_thumbnail_png(image_ds, proc_ds, particle_index: int, *,
                           crop: bool = True, scale: int = 1, probe: str = "2DS") -> bytes:
    """One particle's shadow as a matplotlib-free PNG.

    Wraps :func:`reconstruct_particle_image` and :func:`crop_to_content`
    around :func:`_png_bytes`, the same standard-library writer
    :func:`render_flight_to_disk` already uses for a whole flight -- pulled
    out to a public function so ``arrayprobe.triage_server``'s ``/thumb`` and
    ``/sheet`` routes can call it directly instead of the much slower
    ``matplotlib`` path :func:`render_particle` uses (a private ``Figure`` per
    request, ~50-75 ms measured -- fine for one particle, the reason a
    contact sheet of 200 costs ~10 s).  Byte-for-byte what
    ``render_flight_to_disk`` writes to disk for the same particle and the
    same ``crop``/``scale``.
    """
    c = reconstruct_particle_image(image_ds, proc_ds, particle_index, probe=probe)
    if crop:
        c = crop_to_content(c)
    return _png_bytes(c, scale=scale)


def unverified_placeholder_png(size: int = 48) -> bytes:
    """A small placeholder PNG for a probe outside :data:`DRAWABLE_PROBES`.

    ``arrayprobe.triage_server`` serves this from its ``/thumb`` and grid
    routes instead of calling :func:`reconstruct_particle_image` (and raising
    ``ValueError``) for a probe this module has not verified -- see
    ``DRAWABLE_PROBES``'s own docstring for exactly what is unchecked.
    Matplotlib-free, the same as :func:`particle_thumbnail_png`'s own writer
    and for the same reason: a flight's contact sheet can ask for hundreds of
    these on one page. Text does not fit a bytes-only PNG writer, so this
    carries only a visual "this is not the real image" signal (an X in a
    bordered box); the actual explanation is text in the surrounding page,
    beside wherever this is embedded.
    """
    mask = np.zeros((size, size), dtype=bool)
    idx = np.arange(size)
    mask[idx, idx] = True                 # \
    mask[idx, size - 1 - idx] = True      # /
    mask[0, :] = mask[-1, :] = mask[:, 0] = mask[:, -1] = True  # border
    return _png_bytes(mask)


def _hhmmss(time_value: float) -> str:
    """``73928.0`` -> ``"073928"``.

    The proc file's ``Time`` is MATLAB's HHMMSS packed into a float, not a
    count of seconds, so it is formatted rather than converted.
    """
    return f"{int(round(float(time_value))):06d}"


def classify_particle(reject_code, verdict: str | None) -> str:
    """Which of :data:`PARTICLE_CLASSES` a particle belongs in."""
    if verdict == "unsure":
        return "unsure"
    return "accepted" if bool(is_accepted_code(int(reject_code))) else "rejected"


def render_flight_to_disk(image_ds, proc_ds, out_dir, *, verdicts=None,
                          classes=PARTICLE_CLASSES, scale: int = 3,
                          crop: bool = True, limit=None, progress=None) -> dict:
    """Write every particle of a flight to ``out_dir/<HHMMSS>/<class>/``.

    One directory per second, per the author's own description of what this is
    for: looking at a whole second's worth of particles together rather than at
    a sampled gallery.

    ``classes`` selects which of :data:`PARTICLE_CLASSES` are written, and
    exists because the counts are large -- a single 2017 flight is 436,983
    particles, 87 % of them accepted -- so ``classes=("accepted",)`` is the
    documented way to start.

    **Resumable**: a particle whose PNG is already on disk is skipped, so an
    interrupted run continues rather than restarting. That matters when the run
    is hours long.

    Returns counts per class plus ``skipped`` and ``seconds``.
    """
    from pathlib import Path

    out = Path(out_dir)
    verdicts = verdicts or {}
    wanted = set(classes)
    times = np.asarray(proc_ds.variables["Time"][:])
    rejects = np.asarray(proc_ds.variables["image_auto_reject"][:])
    total = len(times) if limit is None else min(int(limit), len(times))

    counts = {name: 0 for name in PARTICLE_CLASSES}
    counts["skipped"] = 0
    seconds = set()

    for i in range(total):
        entry = verdicts.get(str(i)) or verdicts.get(i)
        verdict = entry.get("verdict") if isinstance(entry, dict) else entry
        cls = classify_particle(rejects[i], verdict)
        if cls not in wanted:
            counts["skipped"] += 1
            continue
        second = _hhmmss(times[i])
        seconds.add(second)
        target = out / second / cls / f"p{i:07d}.png"
        if target.exists():
            counts[cls] += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(particle_thumbnail_png(image_ds, proc_ds, i, crop=crop, scale=scale))
        counts[cls] += 1
        if progress is not None and (i + 1) % 1000 == 0:
            progress(i + 1, total, counts)

    counts["seconds"] = len(seconds)
    return counts


#: Images per index page. A second is not a small unit: on the first real
#: flight rendered, the per-second count ranges from 0 to **53,926**, median 2.
#: One page holding fifty thousand ``<img>`` tags is not browsable however lazy
#: the loading, so a busy second is paginated. Measured, not guessed -- the
#: spread is the reason this constant exists.
INDEX_PAGE_SIZE = 500



def _index_name(page_no: int) -> str:
    """``1`` -> ``index.html``, ``2`` -> ``index-2.html``.

    Page one keeps the plain name so a link to a second's directory works
    whether or not that second turned out to need paginating.
    """
    return "index.html" if page_no == 1 else f"index-{page_no}.html"

def write_flight_index(out_dir, *, title: str | None = None,
                       page_size: int = INDEX_PAGE_SIZE) -> list:
    """Index pages for a tree written by :func:`render_flight_to_disk`.

    One page per second listing that second's particles, and one page for the
    flight listing every second with its per-class counts. Without these the
    tree is only navigable in a file manager, which is not what "look at a
    whole second's particles" means in practice.

    A second holding more than ``page_size`` images is split across
    ``index.html``, ``index-2.html`` and so on, each linking to the others.

    Written from what is *on disk* rather than from the render's own return
    value, so an index built after a resumed or partial run describes the tree
    that actually exists.
    """
    from pathlib import Path

    out = Path(out_dir)
    written = []
    rows = []
    for second_dir in sorted(p for p in out.iterdir() if p.is_dir()):
        per_class = {}
        for cls in PARTICLE_CLASSES:
            files = sorted((second_dir / cls).glob("*.png")) if (second_dir / cls).is_dir() else []
            per_class[cls] = files
        n = sum(len(v) for v in per_class.values())
        if not n:
            continue
        rows.append((second_dir.name, {k: len(v) for k, v in per_class.items()}, n))

        # Flatten to (class, file) so a page boundary can fall inside a class.
        flat = [(cls, f) for cls in PARTICLE_CLASSES for f in per_class[cls]]
        pages = [flat[i:i + page_size] for i in range(0, len(flat), page_size)] or [[]]
        for page_no, chunk in enumerate(pages, start=1):
            blocks, current = [], None
            for cls, f in chunk:
                if cls != current:
                    blocks.append(f'<h2>{cls}</h2><div class="grid">')
                    current = cls
                blocks.append(
                    f'<figure><img src="{cls}/{f.name}" alt="{f.stem}" loading="lazy">'
                    f'<figcaption>{f.stem}</figcaption></figure>')
            body = "".join(blocks) + ("</div>" if blocks else "")
            nav = ""
            if len(pages) > 1:
                links = " ".join(
                    f'<b>{i}</b>' if i == page_no
                    else f'<a href="{_index_name(i)}">{i}</a>'
                    for i in range(1, len(pages) + 1))
                nav = (f'<p>{n} particles in this second, {page_size} per page: {links}</p>')
            page = _index_page(
                f"{second_dir.name} &mdash; {n} particles",
                '<p><a href="../index.html">&larr; all seconds</a></p>' + nav + body + nav)
            target = second_dir / _index_name(page_no)
            target.write_text(page, encoding="utf-8")
            written.append(target)

    listing = "".join(
        f'<tr><td><a href="{s}/index.html">{s}</a></td>'
        + "".join(f'<td class="n">{c[k] or ""}</td>' for k in PARTICLE_CLASSES)
        + f'<td class="n">{n}</td></tr>'
        for s, c, n in rows)
    head = "".join(f"<th>{k}</th>" for k in PARTICLE_CLASSES)
    total = sum(n for _, _, n in rows)
    body = (f"<p>{len(rows)} seconds, {total} particles. One directory per second; "
            f"within each, one directory per class.</p>"
            f"<table><thead><tr><th>second</th>{head}<th>all</th></tr></thead>"
            f"<tbody>{listing}</tbody></table>")
    (out / "index.html").write_text(
        _index_page(title or out.name, body), encoding="utf-8")
    written.append(out / "index.html")
    return written


def _index_page(title: str, body: str) -> str:
    return f"""<!doctype html><meta charset="utf-8"><title>{title}</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 1.5rem; background: #f7f8f9; color: #1d2329; }}
 h1 {{ font-size: 1.25rem; }} h2 {{ font-size: 0.95rem; margin: 1.4rem 0 0.4rem; }}
 h2 .n {{ color: #5c6672; font-weight: 400; }}
 .grid {{ display: grid; gap: 0.5rem;
          grid-template-columns: repeat(auto-fill, minmax(90px, 1fr)); }}
 figure {{ margin: 0; background: #fff; border: 1px solid #d9dee3;
           border-radius: 4px; padding: 0.3rem; }}
 figure img {{ width: 100%; height: auto; display: block; image-rendering: pixelated; }}
 figcaption {{ font: 0.62rem monospace; color: #5c6672; margin-top: 0.2rem; }}
 table {{ border-collapse: collapse; font-size: 0.85rem; }}
 th, td {{ text-align: left; padding: 0.3rem 0.7rem; border-bottom: 1px solid #d9dee3; }}
 td.n, th.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
 a {{ color: #1e6f68; }}
</style>
<h1>{title}</h1>
{body}
"""
