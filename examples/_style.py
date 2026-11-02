# SPDX-License-Identifier: BSD-3-Clause
"""House style for the artifact explainers: one colour, one meaning; fonts >= 9 pt."""
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap

SCALE = "#e6821e"     # orange: the scale bar and nothing else
FLAG = "tab:red"      # flagged / rejected / removed / stuck
KEEP = "tab:blue"     # kept / accepted / the package result
TRUTH = "k"           # truth or reference, drawn dashed (or as an outline)
RULE = "0.45"         # threshold or rule, drawn dashed grey
GRID = "0.85"


def apply():
    plt.rcParams.update({"figure.dpi": 110, "font.size": 11, "axes.titlesize": 12,
                         "axes.labelsize": 11, "xtick.labelsize": 10, "ytick.labelsize": 10,
                         "legend.fontsize": 10, "figure.titlesize": 13})


def scale_bar(ax, um_per_px, length_um=100.0, extent=None, at_top=False):
    """Orange bar, black 'N µm' label on a light box, bottom-left of an image panel."""
    x0, x1, y0, y1 = extent or (*ax.get_xlim(), *sorted(ax.get_ylim()))
    top_down = ax.get_ylim()[0] > ax.get_ylim()[1]
    w, h = x1 - x0, y1 - y0
    n = length_um / um_per_px
    xs = x0 + 0.05 * w
    # bar on the visual bottom unless at_top (then the visual top)
    up = top_down != at_top
    y = (y1 - 0.06 * h) if up else (y0 + 0.06 * h)
    dy = -0.07 * h if up else 0.07 * h
    ax.plot([xs, xs + n], [y, y], color=SCALE, lw=4, solid_capstyle="butt", zorder=5)
    ax.text(xs + n / 2, y + dy, f"{length_um:g} µm", ha="center", va="center", fontsize=10,
            color="k", zorder=6,
            bbox=dict(boxstyle="round,pad=0.2", fc="0.96", ec="0.6", lw=0.5))


def pixels(ax, img, red=None, circle_um=None, um_per_px=10.0, title=None, time_x=False,
           key=False, bar_top=False):
    """Draw a boolean image: black pixels, `red` mask in red, optional dashed enclosing circle
    whose diameter (circle_um) is the size quoted in the title. No ticks; pixel grid; scale bar."""
    img = np.asarray(img, bool)
    if time_x:  # arrays are [slice, diode]; draw time along x as in the OAP primer
        img = img.T
        red = None if red is None else np.asarray(red, bool).T
    n = img.shape[0]
    show = np.zeros(img.shape, int)
    show[img] = 1
    if red is not None:
        show[np.asarray(red, bool)] = 2
    ax.imshow(show, cmap=ListedColormap(["white", "k", FLAG]), vmin=0, vmax=2,
              interpolation="nearest")
    ax.set_xticks(np.arange(-0.5, img.shape[1], 1), minor=True)
    ax.set_yticks(np.arange(-0.5, n, 1), minor=True)
    ax.grid(which="minor", color=GRID, lw=0.3)
    ax.tick_params(which="both", length=0, labelbottom=False, labelleft=False)
    if circle_um is not None:
        pts = np.argwhere(img)
        c = pts.mean(axis=0)
        for k in range(1, 400):                       # centre of the smallest enclosing circle
            far = pts[np.argmax(((pts - c) ** 2).sum(1))]
            c = c + (far - c) / (k + 1)
        ax.add_patch(plt.Circle((c[1], c[0]), circle_um / um_per_px / 2.0, fill=False,
                                ec=RULE, ls="--", lw=1.5, zorder=4))
        ax.set_xlim(-0.5, img.shape[1] - 0.5)
        ax.set_ylim(n - 0.5, -0.5)
    scale_bar(ax, um_per_px, 100.0, (-0.5, img.shape[1] - 0.5, -0.5, n - 0.5), at_top=bar_top)
    if title:
        ax.set_title(title, fontsize=12)
    if key:
        arrow = dict(arrowstyle="-|>", color="0.2", lw=1.2, mutation_scale=12, clip_on=False)
        ax.annotate("", xy=(1.0, -0.04), xytext=(0.0, -0.04), xycoords="axes fraction",
                    textcoords="axes fraction", arrowprops=arrow, annotation_clip=False)
        ax.text(0.5, -0.07, "time (slices) →", transform=ax.transAxes, ha="center",
                va="top", fontsize=10)
        ax.annotate("", xy=(-0.04, 0.0), xytext=(-0.04, 1.0), xycoords="axes fraction",
                    textcoords="axes fraction", arrowprops=arrow, annotation_clip=False)
        ax.text(-0.07, 0.5, "diode number (along the array)", transform=ax.transAxes,
                ha="right", va="center", rotation=90, fontsize=10)


def hist_stack(ax, edges, kept, flagged, outline=None, kept_label="kept", flag_label="flagged",
               outline_label=None):
    """One histogram style: kept (blue) under flagged (red), truth as a black outline."""
    mid = np.sqrt(edges[:-1] * edges[1:])
    w = np.diff(edges)
    hk, _ = np.histogram(kept, edges)
    hf, _ = np.histogram(flagged, edges)
    ax.bar(mid, hk, width=w, color=KEEP, alpha=0.8, label=kept_label)
    ax.bar(mid, hf, width=w, bottom=hk, color=FLAG, alpha=0.85, label=flag_label)
    if outline is not None:
        ho, _ = np.histogram(outline, edges)
        ax.step(mid, ho, where="mid", color=TRUTH, lw=1.3, label=outline_label)
    ax.set_xscale("log")
    ax.set_xlabel("time since the previous particle (s)")
    ax.set_ylabel("particles per bin")
    return mid


def threshold_line(ax, x, label):
    """Grey dashed threshold with its label written on the plot."""
    ax.axvline(x, color=RULE, ls="--", lw=1.5)
    ax.text(x, 0.5, " " + label, transform=ax.get_xaxis_transform(), ha="left", va="center",
            bbox=dict(fc="white", ec="none", alpha=0.85, pad=1),
            fontsize=10, color="0.25")
