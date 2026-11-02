# SPDX-License-Identifier: BSD-3-Clause
"""The one place that names a stage-2 decode: engine and reader decide the extension together.

v3.5's own SPEC decoder (probetype 2: 2D-S, HVPS, 3VCPI; channels ``H`` and ``V``) writes
``<flight>.<channel>.nc`` (``arrayprobe_uiops/spec.py:655``, ``:896``). Every other decode writes
``.cdf``: v3.1.4's readers, and the SEA / PMS / DMT readers both engines share
(``readers/sea.py:259``, ``:280``; ``readers/pms.py:191-193``), so a v3.5 CIP decode is
``<flight>.CIP.cdf``.

Five instance fixes (2026-09-14 to 2026-09-30) each re-derived part of this rule in one
place; two of them keyed it on the engine alone and missed the channel term (``bed81c7``). This
module is the single source, and ``tests/test_decode_suffix_single_source.py`` refuses a new
hard-coded decode spelling anywhere under ``src`` or ``tools``.

The engine comes from the product's own ``.call`` stamp, never from which file exists: a stale
v3.1.4 decode beside a v3.5 proc must not be drawn under it (``46368b2``). It lives in the v3.5
engine because code both engines share lives there.
"""

from __future__ import annotations

import re
from pathlib import Path

from arrayprobe_uiops import provenance

#: Every extension a stage-2 decode can carry.
DECODE_SUFFIXES = (".nc", ".cdf")

#: Channels v3.5's own SPEC decoder writes (probetype 2); ``arrayprobe_uiops/spec.py:655``,
#: ``:896``.
V35_OWN_DECODER_CHANNELS = frozenset({"H", "V"})

#: ``proc.<flight>.<channel>[.diodecorrected].nc`` -> flight stem and channel token.
_PROC_RE = re.compile(r"^proc\.(?P<flight>.+?)\.(?P<channel>[^.]+)(?:\.diodecorrected)?\.nc$")


def decode_suffix(engine: str | None, channel: str) -> str:
    """``".nc"`` iff ``engine == "3.5"`` and ``channel`` is ``H`` or ``V``; ``".cdf"`` otherwise.

    ``.cdf`` covers v3.1.4 on every probe and the SEA / PMS / DMT readers both engines share
    (CIP, PIP, 2DC, 2dc, f2dc, 2dp), which write ``.cdf`` whichever engine ran them.
    """
    return ".nc" if engine == "3.5" and channel in V35_OWN_DECODER_CHANNELS else ".cdf"


def decode_name(stem: str, channel: str, engine: str) -> str:
    """``<stem>.<channel><suffix>``, for a caller that knows the engine before any stamp exists."""
    return f"{stem}.{channel}{decode_suffix(engine, channel)}"


def combined_suffix(engine: str) -> str:
    """``"_2"`` iff ``engine == "3.1.4"`` (``combine_sizedist.m:199``'s own naming, kept so a
    port-validation product matches the archived ORACLES product by name); ``""`` for every
    other engine."""
    return "_2" if engine == "3.1.4" else ""


def combined_name(stem: str, orientation: str, probe: str, engine: str) -> str:
    """``<stem>.combined.<orientation>.<probe><suffix>.cdf``.

    The suffix is :func:`combined_suffix`'s."""
    return f"{stem}.combined.{orientation}.{probe}{combined_suffix(engine)}.cdf"


def existing_combined_path(directory: Path | str, stem: str, orientation: str = "H",
                           probe: str = "2DS", *, legacy_if_missing: bool = False) -> Path:
    """A v3.5 / SODA-2 combined product in ``directory``: the current (no ``_2``) name if that
    file exists, else the pre-2026-10-15 ``_2`` name if that one does. When neither exists it
    returns the current name, or the ``_2`` name with ``legacy_if_missing`` (for a caller naming
    an archived product written before the rename). The ``_2`` name is read only to reach
    products written before the rename."""
    directory = Path(directory)
    names = [directory / combined_name(stem, orientation, probe, e) for e in ("3.5", "3.1.4")]
    return next((p for p in names if p.is_file()), names[1] if legacy_if_missing else names[0])


def strip_combined_suffix(name: str, orientation: str = "H", probe: str = "2DS") -> str:
    """The flight stem of a combined product's file name, under either naming."""
    for engine in ("3.5", "3.1.4"):
        tail = combined_name("", orientation, probe, engine)
        if name.endswith(tail):
            return name.removesuffix(tail)
    return name


def engine_from_stamp(product: Path | str, *, assume_engine: str | None = None) -> str:
    """The engine recorded in ``product``'s ``.call`` stamp.

    A stamp with no ``engine=`` key is a pre-2026-09-15 v3.1.4 stamp and reads as ``"3.1.4"``
    (``run_flight._stamps_equivalent``). No stamp returns ``assume_engine`` when the caller passed
    one, and otherwise raises :class:`arrayprobe.provenance.Unstamped`: nothing here defaults
    silently.
    """
    stamp = provenance.read(product)
    if stamp is None:
        if assume_engine is None:
            raise provenance.Unstamped(product)
        return assume_engine
    return stamp.engine if stamp.engine is not None else "3.1.4"


def decode_path(proc_path: Path | str, *, assume_engine: str | None = None) -> Path:
    """The decode beside ``proc.<flight>.<channel>[.diodecorrected].nc``, named from its stamp.

    The engine is :func:`engine_from_stamp`'s, never chosen by which file exists.
    """
    proc_path = Path(proc_path)
    m = _PROC_RE.match(proc_path.name)
    if m is None:
        raise ValueError(f"{proc_path.name} is not a proc.<flight>.<channel>.nc file")
    engine = engine_from_stamp(proc_path, assume_engine=assume_engine)
    return proc_path.with_name(decode_name(m.group("flight"), m.group("channel"), engine))
