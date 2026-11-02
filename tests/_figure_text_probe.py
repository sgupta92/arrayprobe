# SPDX-License-Identifier: BSD-3-Clause
"""Standalone driver: run one ``paper/figures/fig*.py`` script with
matplotlib's text-drawing calls intercepted, and print what was drawn.

Used by ``test_figure_text_matches_captions.py`` so the interception lives in
one place and no figure script needs its own ``--print-text`` mode -- a
script's calls are recorded from the outside (by patching the matplotlib
classes before the script runs), so a script that never routes its title
through some special convention still gets checked.

Invoke as::

    python.exe _figure_text_probe.py <path-to-fig-script.py>

Prints exactly one line starting with ``DRAWN_TEXT_JSON:`` followed by a JSON
list of every string passed to ``Axes.set_title`` / ``set_xlabel`` /
``set_ylabel`` / ``text`` or ``Figure.suptitle`` / ``text``. Everything else on
stdout/stderr is the script's own and is ignored by the caller.

**Known gap**: legend labels are not captured. Most calls in this project's
figures are bare ``ax.legend(frameon=False, ...)`` with no explicit
``labels=``, pulling labels from each artist's own ``label=`` kwarg set
elsewhere (``ax.plot(..., label=...)``, ``ax.bar(..., label=...)``) -- those
ARE captured if drawn through ``.text()``/``.set_title()`` but not through a
plotted artist's own ``label=``. Left for a future pass; noted rather than
silently claimed complete.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.axes  # noqa: E402
import matplotlib.figure  # noqa: E402

_DRAWN: list[str] = []

#: method name -> how to pull the drawn string out of its call arguments.
#: set_title/set_xlabel/set_ylabel/suptitle take the string as the first
#: positional argument or a named one; text() takes (x, y, s, ...).
_TITLE_LIKE_KWARGS = ("label", "t", "xlabel", "ylabel")


def _extract(name: str, args: tuple, kwargs: dict) -> str | None:
    if name in ("set_title", "set_xlabel", "set_ylabel", "suptitle"):
        if args:
            value = args[0]
        else:
            value = next((kwargs[k] for k in _TITLE_LIKE_KWARGS if k in kwargs), None)
    elif name == "text":
        if len(args) >= 3:
            value = args[2]
        else:
            value = kwargs.get("s")
    else:
        value = None
    return value if isinstance(value, str) else None


def _patch() -> None:
    for cls, names in (
        (matplotlib.axes.Axes, ("set_title", "set_xlabel", "set_ylabel", "text")),
        (matplotlib.figure.Figure, ("suptitle", "text")),
    ):
        for name in names:
            original = getattr(cls, name)

            def wrapper(self, *args, _orig=original, _name=name, **kwargs):
                drawn = _extract(_name, args, kwargs)
                if drawn is not None:
                    _DRAWN.append(drawn)
                return _orig(self, *args, **kwargs)

            setattr(cls, name, wrapper)

    # The probe reads what a script draws; it must never write the script's output. Running
    # a figure script in full used to rewrite the tracked PNGs under paper/figures/ mid-suite
    # (same bytes, new mtime), which made the journal-format PDF read as older than its
    # sources on every full run (2026-09-26). Saving is therefore a no-op here.
    matplotlib.figure.Figure.savefig = lambda self, *args, **kwargs: None


def main() -> int:
    script = Path(sys.argv[1]).resolve()
    _patch()
    spec = importlib.util.spec_from_file_location(script.stem, script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "main"):
        module.main()
    print("DRAWN_TEXT_JSON:" + json.dumps(_DRAWN))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
