# SPDX-License-Identifier: BSD-3-Clause
"""The project-level engine selector -- ``arrayprobe.engine()``.

**Why this exists, and what it supersedes.** Until 2026-09-21 the only selector
was ``uiops.engine()``, which dispatches between the two *UIOOPS* engines and
**raises** if asked for SODA-2 (that module's own docstring, "SODA-2 is not a
version here", author's decision 2026-09-12). Every schematic of the package
nonetheless drew one selector box with three engines under it, and the author
named the contradiction directly:

    *"It's not uiops.engine, it's arrayprobe.engine because the uiops.engine is
    then having arrayprobe soda too, which does not make sense."*

Two ways to make the picture and the code agree: draw SODA-2 as unreachable
from the selector, or make the selector actually reach it and stop naming it
after one upstream. **The author chose the second**, which supersedes the
2026-09-12 decision above. So this module is the selector the diagrams have
been drawing all along:

    import arrayprobe

    eng = arrayprobe.engine()           # v3.5 -- the default
    eng = arrayprobe.engine("3.1.4")    # the archived-product anchor, where installed
    eng = arrayprobe.engine("soda2")    # the SODA-2 lineage

``uiops.engine()`` is unchanged, still works, and is not deprecated. It answers
a narrower question -- *which UIOOPS release* -- and keeps its refusal of SODA-2,
because for that question SODA-2 genuinely is not an answer. This module answers
the broader one: *which of this project's engines*.

**It dispatches; it computes nothing.** No number changes because a call came
through here. There is no state, no arithmetic, and **no engine is imported at
module level** -- ``tests/test_project_selector.py`` asserts all three by
parsing this file and by importing it in a clean subprocess, the same way
``test_uiops_selector.py`` guards ``uiops``.

``arrayprobe`` is both the namespace this selector belongs in and the package
that held the v3.1.4 translation, so ``arrayprobe.engine("3.1.4")`` names
``arrayprobe`` itself. An earlier translation of UIOOPS v3.1.4 reproduced
archived products and is not part of this package; where it is absent, asking
for it raises ``V314EngineAbsent``.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "DEFAULT_ENGINE",
    "ENGINES",
    "Engine",
    "UnknownEngine",
    "engine",
]

#: Every engine this project ships, in the order a reader should meet them:
#: the default first, then the other live upstream, then the anchor.
def engines() -> tuple[str, ...]:
    """The engines installed: v3.5 and SODA-2 always, v3.1.4 only where its engine is."""
    from arrayprobe._v314_lazy import engine_present
    return ("3.5", "soda2", "3.1.4") if engine_present() else ("3.5", "soda2")


ENGINES: tuple[str, ...] = engines()

#: What :func:`engine` returns when the caller names nothing.
DEFAULT_ENGINE: str = "3.5"

#: Spellings accepted for each engine. Deliberately small: a selector that
#: guesses is a selector that silently runs the wrong lineage.
_ALIASES: dict[str, str] = {
    "3.5": "3.5", "v3.5": "3.5", "uiops": "3.5", "uiops-v3.5": "3.5",
    "soda2": "soda2", "soda-2": "soda2", "soda_2": "soda2", "soda": "soda2",
    "3.1.4": "3.1.4", "v3.1.4": "3.1.4", "oracles": "3.1.4",
}

_PACKAGE: dict[str, str] = {
    "3.5": "arrayprobe_uiops",
    "soda2": "arrayprobe_soda2",
    "3.1.4": "arrayprobe",
}

#: Package names that are no longer importable, mapped to the package that
#: replaced each. A user-named module (a configuration file's
#: ``[fidelity].profile_module``, ``--probe-case-module``) written with a
#: retired package name is read under its replacement by ``canonical_module``.
RETIRED_PACKAGES: dict[str, str] = {"arrayprobe_v35": "arrayprobe_uiops"}


def canonical_module(dotted: str) -> str:
    """Return ``dotted`` with a retired leading package name replaced.

    Only an exact match of the first dotted segment against
    ``RETIRED_PACKAGES`` is rewritten, old name to new; every other name is
    returned unchanged. Nothing is matched by prefix or similarity. A value
    that is not a string (a test double standing in for a module name) is
    returned as it is.
    """
    if not isinstance(dotted, str):
        return dotted
    head, sep, rest = dotted.partition(".")
    new = RETIRED_PACKAGES.get(head)
    if new is None:
        return dotted
    return f"{new}{sep}{rest}"


_UPSTREAM: dict[str, str] = {
    "3.5": "UIOOPS v3.5 (MATLAB, McFarquhar group)",
    "soda2": "SODA-2 (IDL, NCAR)",
    "3.1.4": "UIOOPS v3.1.4 (MATLAB, McFarquhar group)",
}

_VALIDATION: dict[str, str] = {
    "3.5": "layer 2 -- whole-program Octave goldens of v3.5's own sources. No "
           "archived product was ever written by v3.5, so layer 1 cannot exist "
           "for it and that gap never closes.",
    "soda2": "layer 2 -- GDL running SODA-2's unmodified .pro sources. UND's "
             "archived output is an independent cross-check, never a "
             "bit-fidelity target.",
    "3.1.4": "layer 1 -- a field campaign's archived product, reproduced cell "
             "by cell. The only engine with an archived product behind it, and "
             "the reason to reach for it.",
}


class UnknownEngine(ValueError):
    """Raised for a name that is not one of this project's engines."""


@dataclass(frozen=True)
class Engine:
    """A chosen engine, and what a reader needs to know about it."""

    name: str

    @property
    def package(self) -> str:
        """The importable package implementing it."""
        return _PACKAGE[self.name]

    @property
    def upstream(self) -> str:
        """The package this engine reproduces, and who wrote it."""
        return _UPSTREAM[self.name]

    @property
    def validation(self) -> str:
        """What results from this engine rest on, in one line."""
        return _VALIDATION[self.name]

    @property
    def is_default(self) -> bool:
        """Whether :func:`engine` returns this one when the caller names nothing.

        Default is not the same as authoritative, and the two are deliberately
        different engines here: v3.5 is the default because it is the
        developers' current source, while the v3.1.4 anchor is the only engine
        that can reproduce an archived product. A figure that needs layer-1
        evidence reaches for the anchor whatever this says.
        """
        return self.name == DEFAULT_ENGINE

    @property
    def is_uiops(self) -> bool:
        """Whether ``uiops.engine()`` can also answer for this one."""
        return self.name in ("3.5", "3.1.4")

    def load(self):
        """Import and return the engine's package.

        The import happens **here**, on demand, and never at module level --
        which is what lets this selector be imported without pulling three
        engines into the process.  Where the v3.1.4 engine is not installed (the public
        distribution), ``arrayprobe`` alone would import and answer for it, so this raises
        :class:`~arrayprobe._v314_lazy.V314EngineAbsent` instead.
        """
        import importlib

        if self.name == "3.1.4":
            from arrayprobe._v314_lazy import ABSENT_MESSAGE, V314EngineAbsent, engine_present
            if not engine_present():
                raise V314EngineAbsent(ABSENT_MESSAGE)
        return importlib.import_module(self.package)


def engine(name: str | None = None) -> Engine:
    """The engine called ``name``, or the default if none is named.

    Accepts the engine's version (``"3.5"``), its lineage
    (``"soda2"``), or a small set of obvious spellings. Anything else raises
    :class:`UnknownEngine` naming what is available -- a selector that falls
    through to a default would silently run the wrong lineage.
    """
    if name is None:
        return Engine(DEFAULT_ENGINE)
    key = str(name).strip().lower()
    if key not in _ALIASES:
        raise UnknownEngine(
            f"unknown engine {name!r}. This project offers {list(engines())} "
            f"(default {DEFAULT_ENGINE!r}); accepted spellings are "
            f"{sorted(k for k, v in _ALIASES.items() if v in engines())}.")
    chosen = _ALIASES[key]
    if chosen == "3.1.4" and chosen not in engines():
        from arrayprobe._v314_lazy import ABSENT_MESSAGE, V314EngineAbsent
        raise V314EngineAbsent(ABSENT_MESSAGE)
    return Engine(chosen)
