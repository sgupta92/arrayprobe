# SPDX-License-Identifier: BSD-3-Clause
"""One parser for every ``.call`` provenance sidecar this project writes -- and ``None`` when a
product has none.

**Why this module exists** (2026-09-18). A 1.25 GB CIP product was described as a v3.5
product for a full day when the v3.1.4 engine wrote it. The cause was not inattention; it was
shipped code. ``src/arrayprobe/cli.py:1027`` reads::

    stamped = "3.5" if stamp.startswith("engine=3.5 ") else "3.1.4"

so an *absent* stamp (``OSError -> ""``), a JSON stamp, a truncated stamp and a genuine v3.1.4
stamp are all read as ``"3.1.4"``. Absence and a positive declaration are indistinguishable by
construction, and no amount of care at the keyboard can tell them apart afterwards.

**The contract, and the one rule that matters.** :attr:`Stamp.engine` is ``"3.1.4"``, ``"3.5"``,
``"soda2"`` or ``None``. ``None`` means *the stamp does not record an engine* -- it is never
filled in from a date, a filename, a directory, a sibling file or a default. A caller that needs
a definite engine asks :func:`engine_of`, which raises rather than guesses. That is the whole
point: this module is allowed to say "I do not know", and every consumer is thereby forced to.

**Five formats, one parser.** All five are in the repository today (measured 2026-09-18):

``driver``
    ``scripts/run_flight.py``'s one-line text, ``engine=3.1.4 profile=oracles-production
    reject=(...) shadow_diode=none``. Written by :func:`write_stamp` there and by :func:`write`
    here, character for character the same shape -- ``tests/test_run_from_config.py``'s
    ``ValidatedCallStampsAreByteIdentical`` pins that text and this module does not move it.
    A v3.1.4 stamp written before 2026-09-15 has no ``engine=`` key at all, and is therefore
    ``engine=None`` here. ``scripts/run_flight.py:_stamps_equivalent`` still reads such a stamp as
    v3.1.4 *for the purpose of resume equality*, which is a different question with a different
    safe answer (is this the same configuration I am about to run?); this module answers "what
    wrote it", where the honest answer is that the file does not say.

``v35-combine``
    ``arrayprobe_uiops/combine.py``'s two-line text: the driver shape on line 1
    (``engine=3.5 combine=borrowed-oracles-fork:combine_sizedist.m opt_in=...``) plus
    ``inputs=<names>`` on line 2; through ``scripts/run_flight.py``, a third line
    ``inputs_built_with=(<the inputs' stamp>)``.

``soda2-pbp``
    ``cli.py``'s ``.pbp.call`` JSON, whose ``"engine"`` key is the string ``"soda2"``.

``legacy-json``
    The four hand-rolled JSON dicts the ``_decoded/`` lane scripts write (``stage``/``profile``/
    ``reject``; ``stage``/``tree``/``tas_source``; ...). **None of them carries an engine key**, so
    every one of them is ``engine=None``. This is the format the CIP product carries, and reading
    it as v3.1.4 is precisely the failure above.

``unparseable``
    A stamp that exists and is neither key=value text nor JSON -- a truncation, most likely.
    It is deliberately not folded into ``unstamped``: saying "no stamp" about a file that has one
    is the same class of untruth this module exists to stop.

**Stdlib only, and no arithmetic on data.** Nothing here reads a product's contents, so importing
it costs nothing and it can be imported from any engine, any tool and any lane script. It is a
``TOOLING`` module in :data:`uiops.CATALOGUE`.

**It lives in the v3.5 engine** (moved from ``arrayprobe/provenance.py`` 2026-09-30):
code both engines share lives here, so deleting the v3.1.4 package breaks nothing that reads a
stamp. ``arrayprobe.provenance`` remains as an alias of this module for the v3.1.4 callers.

**A sidecar is keyed by name, so it does not survive a hardlink, copy or rename** -- the product
carries nothing inside it. :func:`report` prints ``nlink`` for exactly that reason. Whether the
products should carry two global attributes instead is an open design question
; until it is settled, a stamp is
what there is.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "ATTR_CALL",
    "ATTR_ENGINE",
    "ATTR_PREFIX",
    "ATTR_PROFILE",
    "ATTR_STAGE",
    "CALL_SUFFIX",
    "ENGINES",
    "EngineUnrecorded",
    "FORMATS",
    "PROFILE_UNSTATED",
    "PROVENANCE_ATTRS",
    "engine_attrs",
    "ProvenanceDisagreement",
    "STATES",
    "Stamp",
    "Unstamped",
    "attrs_for",
    "call_path",
    "disagreements",
    "engine_of",
    "is_provenance_attr",
    "parse",
    "read",
    "read_in_file_stamp",
    "read_text",
    "report",
    "require",
    "stamp_from_attrs",
    "stamp_text",
    "state",
    "write",
]

#: ``scripts/run_flight.py:call_path``'s naming: the stamp lives beside the product, never inside
#: it.
CALL_SUFFIX = ".call"

#: Every engine name a stamp may record. ``None`` -- not in this tuple -- is the fourth answer.
ENGINES: tuple[str, ...] = ("3.1.4", "3.5", "soda2")

#: Every value :attr:`Stamp.format` may take.
FORMATS: tuple[str, ...] = ("driver", "v35-combine", "soda2-pbp", "legacy-json", "unparseable")

#: Every value :func:`state` may return. ``unparseable`` extends the four-format set on purpose;
#: see the module docstring.
STATES: tuple[str, ...] = (
    "stamped", "unstamped", "orphan-stamp", "in-flight", "legacy-json", "unparseable",
)

#: The prefix every provenance **global attribute** carries (2026-09-18).
#:
#: A sidecar is keyed by filename, so a rename, copy or hardlink drops it -- which is exactly how a
#: 1.25 GB v3.1.4 CIP product came to be indexed under a name carrying no stamp at all. An
#: attribute travels with the bytes.
#:
#: The prefix is lowercase-with-underscores on purpose. Every attribute UIOOPS itself writes is
#: Title Case, usually with a space (``'Creation Time'``, ``'SA Method'``, ``'Data Source'``,
#: ``'Dmax Definition'``), so nothing here can collide with the output contract, and
#: :func:`is_provenance_attr` can recognise ours **by shape** rather than by an enumerated list
#: that would silently stop covering a name added later.
ATTR_PREFIX = "arrayprobe_"

#: The engine that wrote the file: one of :data:`ENGINES`, never a default.
ATTR_ENGINE = ATTR_PREFIX + "engine"

#: The fidelity profile, when the stage takes one.
ATTR_PROFILE = ATTR_PREFIX + "profile"

#: The stage, when the writer names one.
ATTR_STAGE = ATTR_PREFIX + "stage"

#: The whole stamp text, character for character what the ``.call`` sidecar holds -- both are
#: built by :func:`stamp_text`, so they cannot drift by construction. This is the record; the three
#: keys above are the same information split out so ``ncdump -h`` is readable without a parser.
ATTR_CALL = ATTR_PREFIX + "call"

#: Every provenance attribute name this module writes.
#:
#: **This is deliberately NOT a second ``VOLATILE_ATTRS``**
#: (the pipeline benchmark's set). That set means *"differs between two otherwise-identical
#: runs"* -- ``'Creation Time'`` and nothing else, pinned by
#: ``tests/test_benchmark_fidelity_gate.py``. These attributes are the opposite: deterministic,
#: meaningful, and exactly what a digest should catch. The two comparisons want opposite answers:
#:
#: ===========================================  ===========================================
#: our run vs our run (parallel/JIT identity)   **compared** -- a differing engine must fail
#: our run vs an archived MATLAB product        **excluded** -- the archive cannot carry it
#: ===========================================  ===========================================
#:
#: So the *comparison* names the sets it excludes; the attribute does not declare itself volatile.
#: A byte-identity gate excludes ``VOLATILE_ATTRS`` alone and therefore already compares these; a
#: layer-1 comparison against an archived product excludes ``VOLATILE_ATTRS | PROVENANCE_ATTRS``.
#: Folding these into ``VOLATILE_ATTRS`` would blind the first comparison to a run made by the
#: wrong engine, which is the failure these attributes exist to stop.
PROVENANCE_ATTRS = frozenset({ATTR_ENGINE, ATTR_PROFILE, ATTR_STAGE, ATTR_CALL})

#: A stamp key: an identifier at the start of the line or after whitespace, followed by ``=``.
#: The whitespace requirement keeps ``reject=(rej_hollow=0,max_edge_img_ar=4)`` one value instead
#: of three keys -- its inner ``=`` signs are preceded by ``(`` or ``,``, never by a space
#: (``scripts/run_flight.py`` builds that fragment with ``",".join(...)``). Same algorithm as
#: ``arrayprobe.attributed_export.parse_stamp``, which predates this module and should delegate
#: here; it is not imported because it pulls in numpy and netCDF4 and this module is stdlib-only.
_STAMP_KEY = re.compile(r"(?:^|\s)([A-Za-z_][A-Za-z0-9_.]*)=")

#: What marks ``arrayprobe_uiops/combine.py``'s mirrored stamp as its own format rather than a
#: driver stamp that happens to say ``engine=3.5``.
_V35_COMBINE_MARK = "combine=borrowed-oracles-fork:"

#: Products a directory sweep considers. A lane directory also holds ``.csv``, ``.json`` and logs;
#: none of them is a stage output that carries a stamp.
_PRODUCT_SUFFIXES = (".nc", ".cdf")


class Unstamped(Exception):
    """A product carries no ``.call`` sidecar, so nothing is recorded about what wrote it."""

    def __init__(self, product: Path | str) -> None:
        self.product = Path(product)
        super().__init__(
            f"{self.product.name} carries no {CALL_SUFFIX} sidecar, so what wrote it is not "
            f"recorded. Run `arrayprobe provenance {self.product}` for the full picture. "
            f"Nothing here infers an engine from a date, a filename or a neighbouring file."
        )


class EngineUnrecorded(Exception):
    """A product *has* a stamp, and that stamp does not name an engine.

    Distinct from :class:`Unstamped` because the two call for different answers: an unstamped file
    may simply predate stamping, while a stamp that exists and is silent on the engine is a format
    that never had the field (every ``legacy-json`` lane stamp, and every driver stamp written
    before 2026-09-15).
    """

    def __init__(self, product: Path | str, stamp: Stamp) -> None:
        self.product = Path(product)
        self.stamp = stamp
        super().__init__(
            f"{self.product.name}'s {CALL_SUFFIX} stamp is {stamp.format!r} and records no "
            f"engine. It is not v3.1.4 by default -- that guess is the defect this refusal "
            f"exists to prevent. Re-run the stage through a stamping path, or annotate "
            f"it."
        )


class ProvenanceDisagreement(Exception):
    """The attribute inside a product and the ``.call`` sidecar beside it say different things.

    **Never resolved silently.** The attribute is additive -- it does not outrank the sidecar and
    the sidecar does not outrank it -- so a disagreement is a finding about the product, not a tie
    to break. Picking a winner here would manufacture exactly the confident-but-wrong answer that
    this module exists to stop; raising hands the question to whoever can actually settle it.

    ``differences`` is the list :func:`disagreements` produced, one line per field that both
    carriers state and state differently.
    """

    def __init__(self, product: Path | str, differences: list[str]) -> None:
        self.product = Path(product)
        self.differences = list(differences)
        joined = "; ".join(self.differences)
        super().__init__(
            f"{self.product.name}: the provenance attribute inside the file and the "
            f"{CALL_SUFFIX} sidecar beside it disagree -- {joined}. Neither wins by default: one "
            f"of them describes a run that did not write these bytes. Re-run the stage, or decide "
            f"which is true; `arrayprobe provenance {self.product}` shows both."
        )


@dataclass(frozen=True)
class Stamp:
    """One parsed ``.call`` sidecar.

    ``engine`` is ``None`` whenever the stamp does not say. ``raw`` is the sidecar's text verbatim,
    because the parsed keys are a convenience and the raw line is the record.
    """

    format: str
    engine: str | None
    profile: str | None
    stage: str | None
    raw: str
    fields: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.format not in FORMATS:
            raise ValueError(f"format {self.format!r} is not one of {FORMATS}")
        if self.engine is not None and self.engine not in ENGINES:
            raise ValueError(f"engine {self.engine!r} is not one of {ENGINES} (or None)")


def call_path(product: Path | str) -> Path:
    """Where ``product``'s stamp lives: ``<product><CALL_SUFFIX>``, beside it, never inside it."""
    p = Path(product)
    return p.with_name(p.name + CALL_SUFFIX)


def read_text(product: Path | str) -> str | None:
    """``product``'s stamp text, or ``None`` if it has none.

    An unreadable sidecar is ``None`` too -- no stamp and a stamp we cannot open are the same
    epistemic state, and neither is an engine.
    """
    sidecar = call_path(product)
    try:
        return sidecar.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _parse_keyvalue(text: str) -> dict[str, str] | None:
    """``"engine=3.1.4 profile=x"`` -> its pairs, or ``None`` if the text is not that shape.

    Values may contain spaces (``area_ratio_z=0.5 (default)``) and nested ``=`` signs
    (``reject=(rej_hollow=0,...)``), so this is not a ``split()``: each key's value runs to the
    start of the next key. A duplicated key returns ``None`` -- refusing to pick one, because
    silently keeping one of two contradictory values is how a stamp stops meaning anything.
    """
    stripped = text.strip()
    if not stripped:
        return None
    hits = list(_STAMP_KEY.finditer(stripped))
    if not hits or hits[0].start() != 0:
        return None
    out: dict[str, str] = {}
    for i, hit in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(stripped)
        key = hit.group(1)
        if key in out:
            return None
        out[key] = stripped[hit.end():end].strip()
    return out


def _engine_from(value: Any) -> str | None:
    """A recorded engine value -> a name in :data:`ENGINES`, or ``None``.

    An engine this module does not know is ``None`` rather than passed through: a consumer
    dispatching on an unrecognised string is the same failure as one dispatching on a guess.
    """
    if not isinstance(value, str):
        return None
    name = value.strip()
    return name if name in ENGINES else None


def parse(text: str) -> Stamp:
    """Parse stamp ``text`` in whichever of the five formats it is written in.

    Detection is by content, not by filename: a ``.pbp.call`` renamed does not stop being SODA-2
    JSON, and a lane script's JSON does not become a driver stamp by sitting next to a ``proc``.
    """
    raw = text.strip()
    if not raw:
        return Stamp("unparseable", None, None, None, raw, {})

    if raw.startswith("{"):
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError:
            return Stamp("unparseable", None, None, None, raw, {})
        if not isinstance(doc, dict):
            return Stamp("unparseable", None, None, None, raw, {})
        fields = {str(k): ("" if v is None else str(v)) for k, v in doc.items()}
        engine = _engine_from(doc.get("engine"))
        profile = doc.get("profile")
        stage = doc.get("stage")
        fmt = "soda2-pbp" if engine == "soda2" else "legacy-json"
        # A lane JSON has no engine key at all. That is not v3.1.4; it is silence.
        return Stamp(
            fmt,
            engine,
            str(profile) if isinstance(profile, str) else None,
            str(stage) if isinstance(stage, str) else None,
            raw,
            fields,
        )

    first = raw.splitlines()[0] if raw.splitlines() else raw
    pairs = _parse_keyvalue(first)
    if pairs is None:
        return Stamp("unparseable", None, None, None, raw, {})
    fields = dict(pairs)
    for line in raw.splitlines()[1:]:
        extra = _parse_keyvalue(line)
        if extra:
            for k, v in extra.items():
                fields.setdefault(k, v)
    fmt = "v35-combine" if _V35_COMBINE_MARK in raw else "driver"
    return Stamp(
        fmt,
        _engine_from(fields.get("engine")),
        fields.get("profile"),
        fields.get("stage"),
        raw,
        fields,
    )


def read(product: Path | str) -> Stamp | None:
    """``product``'s parsed stamp, or ``None`` when it has no sidecar."""
    text = read_text(product)
    return None if text is None else parse(text)


def require(product: Path | str) -> Stamp:
    """``product``'s stamp, raising :class:`Unstamped` when there is none."""
    stamp = read(product)
    if stamp is None:
        raise Unstamped(product)
    return stamp


def engine_of(product: Path | str) -> str:
    """The engine that wrote ``product``, from its own stamp.

    Raises :class:`Unstamped` when there is no sidecar and :class:`EngineUnrecorded` when there is
    one that does not name an engine. It never returns a default; there is no code path here that
    produces an engine name the stamp did not contain.
    """
    stamp = require(product)
    if stamp.engine is None:
        raise EngineUnrecorded(product, stamp)
    return stamp.engine


def stamp_text(
    *,
    engine: str,
    # REQUIRED, not defaulted: `profile=None` is a legal and meaningful value here
    # -- an S2 stamp names no profile because neither the SEA nor the DMT reader
    # reads one -- but it must be STATED. A default cannot distinguish "absent by
    # design" from "the caller forgot", which is the whole point of
    # tests/test_profile_is_never_defaulted.py, and that check caught this module
    # propagating the anti-pattern across four signatures on 2026-09-18.
    profile: str | None,
    stage: str | None = None,
    extra: dict[str, str] | None = None,
) -> str:
    """The one-line driver-format stamp text, with no trailing newline.

    **Both carriers are built from here** -- :func:`write` writes this plus ``"\\n"`` into the
    sidecar, :func:`attrs_for` puts this into :data:`ATTR_CALL` -- so the attribute and the sidecar
    are byte-identical by construction rather than by anyone remembering to keep them so. That is
    what stops the attribute becoming a second source of truth: there is one text, stored twice.

    Raises ``ValueError`` on an engine outside :data:`ENGINES`, or on a value containing a newline
    or a space-separated ``word=`` (which would re-parse as a second key and quietly change what
    the stamp says).
    """
    if engine not in ENGINES:
        raise ValueError(f"engine {engine!r} is not one of {ENGINES}")
    pairs: list[tuple[str, str]] = [("engine", engine)]
    if profile is not None:
        pairs.append(("profile", profile))
    if stage is not None:
        pairs.append(("stage", stage))
    pairs.extend(sorted((extra or {}).items()))
    for key, value in pairs:
        text = str(value)
        if "\n" in text or "\r" in text:
            raise ValueError(f"stamp value for {key!r} contains a newline: {text!r}")
        if _STAMP_KEY.search(" " + text):
            raise ValueError(
                f"stamp value for {key!r} contains a space-separated 'word=', which would re-parse "
                f"as a second key: {text!r}"
            )
    return " ".join(f"{k}={v}" for k, v in pairs)


def is_provenance_attr(name: str) -> bool:
    """Whether ``name`` is one of this project's provenance global attributes.

    By prefix, not by membership of :data:`PROVENANCE_ATTRS`, so a comparison that excludes
    "our provenance" keeps excluding all of it when a fourth key is added later. A check that
    enumerates is a check that silently stops covering things.
    """
    return name.startswith(ATTR_PREFIX)


def attrs_for(
    *,
    engine: str,
    # REQUIRED, not defaulted: `profile=None` is a legal and meaningful value here
    # -- an S2 stamp names no profile because neither the SEA nor the DMT reader
    # reads one -- but it must be STATED. A default cannot distinguish "absent by
    # design" from "the caller forgot", which is the whole point of
    # tests/test_profile_is_never_defaulted.py, and that check caught this module
    # propagating the anti-pattern across four signatures on 2026-09-18.
    profile: str | None,
    stage: str | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """The global attributes that record this configuration, ready for ``putAtt``.

    Pure ``str`` in, pure ``dict[str, str]`` out -- no netCDF here, so this module stays
    stdlib-only and a lane script can import it. :func:`arrayprobe_uiops.ncio.put_provenance` is
    what
    writes them.
    """
    text = stamp_text(engine=engine, profile=profile, stage=stage, extra=extra)
    attrs = {ATTR_CALL: text, ATTR_ENGINE: engine}
    if profile is not None:
        attrs[ATTR_PROFILE] = str(profile)
    if stage is not None:
        attrs[ATTR_STAGE] = str(stage)
    return attrs


#: The value :data:`ATTR_PROFILE` carries when a library caller of the v3.5 or SODA-2 engine
#: named no profile (author, 2026-09-24). It is deliberately not a profile name: those engines
#: take thresholds, not a profile, so a bare library call has none to record, and inventing one
#: from the thresholds would be inference. :func:`stamp_from_attrs` reads it as *silence* (no
#: profile recorded), so it never disagrees with a sidecar that names one.
PROFILE_UNSTATED = "unstated"


def engine_attrs(*, engine: str, profile: str | None) -> dict[str, str]:
    """The two global attributes every v3.5 and SODA-2 product carries.

    ``{ATTR_ENGINE: engine, ATTR_PROFILE: profile or PROFILE_UNSTATED}``, in that order. Written
    unconditionally by those engines' writers -- a product that is copied, renamed or hardlinked
    still says what wrote it. **Never written by the earlier translation**, whose products must stay
    byte-faithful to MATLAB's; there the opt-in :func:`arrayprobe_uiops.ncio.put_provenance`
    remains.
    ``profile`` is required but may be ``None``: ``None`` writes :data:`PROFILE_UNSTATED`.
    """
    if engine not in ("3.5", "soda2"):
        raise ValueError(f"engine_attrs is for the v3.5 and SODA-2 engines only, not {engine!r}")
    text = PROFILE_UNSTATED if profile is None else str(profile)
    if not text or any(c in text for c in " \r\n") or _STAMP_KEY.search(" " + text):
        raise ValueError(f"profile {text!r} cannot be carried as a stamp value")
    return {ATTR_ENGINE: engine, ATTR_PROFILE: text}


def stamp_from_attrs(attrs: dict[str, Any]) -> Stamp | None:
    """The :class:`Stamp` a product's own global attributes record, or ``None`` if it has none.

    Reads through :func:`parse`, the same parser the sidecar goes through -- there is deliberately
    no second parser for the attribute form. :data:`ATTR_CALL` is the record when present; the
    discrete keys are re-assembled into the same text when it is not (a hand-annotated file, or a
    future writer that sets only the engine).

    Raises :class:`ProvenanceDisagreement` when the file's own keys contradict its own
    :data:`ATTR_CALL` -- which :func:`attrs_for` cannot produce, so it means the file was edited.
    """
    present = {str(k): v for k, v in attrs.items() if is_provenance_attr(str(k))}
    if not present:
        return None
    call = present.get(ATTR_CALL)
    if call is not None:
        stamp = parse(str(call))
    else:
        discrete = [
            (key, str(present[attr]))
            for attr, key in ((ATTR_ENGINE, "engine"), (ATTR_PROFILE, "profile"),
                              (ATTR_STAGE, "stage"))
            if attr in present
            # PROFILE_UNSTATED is silence, not a profile named "unstated".
            and not (attr == ATTR_PROFILE and str(present[attr]) == PROFILE_UNSTATED)
        ]
        # Assembled, not validated: an engine name this module does not know must reach
        # ``parse`` and come back as ``engine=None``, not raise -- silence is the honest answer
        # for a value we cannot vouch for, and ``stamp_text`` would refuse it outright.
        stamp = parse(" ".join(f"{k}={v}" for k, v in discrete))
    internal: list[str] = []
    if call is not None:
        for attr, key in ((ATTR_ENGINE, "engine"), (ATTR_PROFILE, "profile"),
                          (ATTR_STAGE, "stage")):
            if attr not in present:
                continue
            if str(present[attr]) != (getattr(stamp, key) or ""):
                internal.append(
                    f"{attr}={str(present[attr])!r} but {ATTR_CALL} says "
                    f"{getattr(stamp, key)!r}"
                )
    if internal:
        raise ProvenanceDisagreement("<attributes>", internal)
    return stamp


def disagreements(sidecar: Stamp | None, inside: Stamp | None) -> list[str]:
    """Every field the two carriers **both state** and state differently.

    **Silence is not disagreement.** A sidecar that records no engine (every ``legacy-json`` lane
    stamp, and every driver stamp written before 2026-09-15) against an attribute that names one
    is the attribute supplying what the sidecar lacks -- the point of carrying provenance in the
    file, not a finding. Only a field both sides fill, with different values, is reported. Extra
    keys on either side are
    likewise not a difference: the sidecar may carry a ``reject=(...)`` fragment no attribute
    holds, and saying so on every product would train the reader to ignore the check.
    """
    if sidecar is None or inside is None:
        return []
    out: list[str] = []
    for key in ("engine", "profile", "stage"):
        theirs, ours = getattr(sidecar, key), getattr(inside, key)
        if theirs is not None and ours is not None and theirs != ours:
            out.append(f"{key}: sidecar says {theirs!r}, attribute says {ours!r}")
    for key, ours_value in sorted(inside.fields.items()):
        if key in ("engine", "profile", "stage"):
            continue
        theirs_value = sidecar.fields.get(key)
        if theirs_value is not None and theirs_value != ours_value:
            out.append(f"{key}: sidecar says {theirs_value!r}, attribute says {ours_value!r}")
    return out


def write(
    product: Path | str,
    *,
    engine: str,
    # REQUIRED, not defaulted: `profile=None` is a legal and meaningful value here
    # -- an S2 stamp names no profile because neither the SEA nor the DMT reader
    # reads one -- but it must be STATED. A default cannot distinguish "absent by
    # design" from "the caller forgot", which is the whole point of
    # tests/test_profile_is_never_defaulted.py, and that check caught this module
    # propagating the anti-pattern across four signatures on 2026-09-18.
    profile: str | None,
    stage: str | None = None,
    extra: dict[str, str] | None = None,
) -> Path:
    """Stamp ``product`` in the **driver text format**, partial-then-rename.

    The text shape mirrors ``scripts/run_flight.py:write_stamp`` deliberately, so that a product
    stamped by a single-stage CLI verb and one stamped by the driver are read by the same parser
    and compare by the same string rules. Partial-then-``os.replace`` is not decoration: a kill
    mid-write would otherwise leave a truncated stamp, which compares unequal and silently costs a
    redo -- or, worse, compares equal to a prefix of some future label.

    Returns the sidecar path. Raises ``ValueError`` on an engine outside :data:`ENGINES`, or on a
    value containing a newline or a space-separated ``word=`` (which would re-parse as a second
    key and quietly change what the stamp says).
    """
    label = stamp_text(engine=engine, profile=profile, stage=stage, extra=extra)
    sidecar = call_path(product)
    partial = sidecar.with_name(sidecar.name + ".partial")
    partial.write_text(label + "\n", encoding="utf-8")
    os.replace(partial, sidecar)
    return sidecar


def _in_flight(product: Path) -> bool:
    """Whether a run appears to be writing ``product`` right now.

    Two conventions are in the tree: ``<product>.partial`` (the stamp writer's and the stage
    writers' rename dance) and an ``_inflight/`` directory beside the product holding the stem.
    """
    if product.with_name(product.name + ".partial").exists():
        return True
    inflight = product.parent / "_inflight"
    if inflight.is_dir():
        stem = product.name.split(".")[0]
        for entry in inflight.iterdir():
            if entry.name.startswith(stem):
                return True
    return False


def state(product: Path | str) -> str:
    """One of :data:`STATES`, for one product path.

    ``orphan-stamp`` is a sidecar whose product is gone -- five of them sit in
    ``_decoded/cip160906/`` alone. ``in-flight`` outranks the rest because a partial file's
    missing stamp is expected, not a finding.
    """
    p = Path(product)
    exists = p.exists()
    stamp = read(p)
    if _in_flight(p):
        return "in-flight"
    if not exists:
        return "orphan-stamp" if stamp is not None else "unstamped"
    if stamp is None:
        return "unstamped"
    if stamp.format == "legacy-json":
        return "legacy-json"
    if stamp.format == "unparseable":
        return "unparseable"
    return "stamped"


def _checkout_sha() -> str:
    """This checkout's ``git rev-parse HEAD`` plus a dirty flag -- *not* the product's.

    Deliberately never written into a stamp: adding
    ``source=<sha>`` to the driver text would break byte-identity with every validated sidecar.
    Reported here and labelled, which is honest and costs nothing.
    """
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10,
        )
        if sha.returncode != 0:
            return "unknown (not a git checkout)"
        head = sha.stdout.strip()[:12]
        status = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, timeout=10,
        )
        dirty = " dirty" if status.returncode == 0 and status.stdout.strip() else ""
        return f"{head}{dirty}"
    except (OSError, subprocess.SubprocessError):
        return "unknown (git unavailable)"


def _expand(paths: Iterable[Path | str]) -> list[Path]:
    """Every path a report should cover: a file as itself, a directory as its products.

    A directory expands to every ``*.nc``/``*.cdf`` in it **plus** the product path implied by
    every orphan ``.call``, so a sidecar whose product has been deleted is still reported. Silence
    about a directory is what let 16 unstamped products accumulate unremarked.
    """
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            found = {q for q in p.iterdir() if q.suffix in _PRODUCT_SUFFIXES and q.is_file()}
            for sidecar in p.glob("*" + CALL_SUFFIX):
                found.add(sidecar.with_name(sidecar.name[: -len(CALL_SUFFIX)]))
            out.extend(sorted(found, key=lambda q: q.name))
        else:
            out.append(p)
    return out


def _nlink(p: Path) -> str:
    try:
        return str(os.stat(p).st_nlink)
    except OSError:
        return "-"


def report(paths: Iterable[Path | str], *, require: bool = False) -> tuple[str, int]:
    """The ``arrayprobe provenance`` table, and an exit code.

    Returns ``(text, code)``. With ``require=True`` the code is ``1`` unless every reported
    product is ``stamped`` **and names an engine**. The second half is not redundant: a driver
    stamp written before 2026-09-15 has no ``engine=`` key, so it is legitimately ``stamped`` --
    the sidecar is there and records the whole configuration -- while still not saying what wrote
    the file. Passing it would let ``--require`` green-light exactly the products of
    unrecorded engine this module exists to catch.
    A directory answer is never silent: an empty directory says so, which is how the two-empty-
    trees reading of "there is nothing here" is prevented.

    ``nlink`` is printed because a sidecar is keyed by name: a product with ``nlink > 1`` has at
    least one other name, and that other name has no stamp of its own.
    """
    targets = _expand(paths)
    lines: list[str] = []
    header = (f"{'product':<40} {'state':<13} {'engine':<11} {'format':<13} {'nlink':>5}  "
              f"{'profile':<20} in-file")
    lines.append(header)
    lines.append("-" * len(header))
    counts: dict[str, int] = {}
    not_stamped = 0
    no_engine = 0
    disagree = 0
    for p in targets:
        st = state(p)
        counts[st] = counts.get(st, 0) + 1
        stamp = read(p)
        inside = _inside(p)
        engine = (stamp.engine if stamp else None) or "unrecorded"
        fmt = stamp.format if stamp else "-"
        profile = (stamp.profile if stamp else None) or "-"
        differences = disagreements(stamp, inside)
        if differences:
            in_file = "DISAGREES: " + "; ".join(differences)
            disagree += 1
        elif inside is not None:
            in_file = f"engine={inside.engine or '-'} profile={inside.profile or '-'}"
        else:
            in_file = "-"
        lines.append(
            f"{p.name:<40} {st:<13} {engine:<11} {fmt:<13} {_nlink(p):>5}  {profile:<20} {in_file}"
        )
        if st == "unstamped" and inside is not None and inside.engine:
            pass  # the in-file stamp alone accounts for it, as ncio.provenance_of accepts
        elif st != "stamped":
            not_stamped += 1
        elif stamp is None or stamp.engine is None:
            no_engine += 1
    if not targets:
        lines.append("(no products found -- an empty answer, stated rather than implied)")
    lines.append("")
    lines.append("counts: " + (", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"))
    lines.append(f"checkout: {_checkout_sha()}  (this checkout, not the product's -- no stamp "
                 f"records the source tree that wrote it)")
    lines.append("note: a stamp is keyed by name; a copy, hardlink or rename loses it. The in-file "
                 "column reads the product's own arrayprobe_* attributes, which survive all three.")
    failures = not_stamped + no_engine + disagree
    if require and failures:
        lines.append(
            f"REQUIRE: {failures} of {len(targets)} product(s) unaccounted for "
            f"({not_stamped} not `stamped`, {no_engine} stamped but naming no engine, "
            f"{disagree} whose sidecar and in-file stamp disagree)."
        )
    code = 1 if (require and failures) else 0
    return "\n".join(lines) + "\n", code


def read_in_file_stamp(filename: str | os.PathLike[str]) -> Stamp | None:
    """The stamp ``filename`` carries **in its own bytes** (its global attributes), or ``None`` if
    it carries none.

    Survives a rename, a copy and a hardlink, which a ``.call`` sidecar keyed by filename does not.
    ``netCDF4`` is imported here rather than at module load, so importing this module stays cheap.
    """
    from netCDF4 import Dataset

    with Dataset(filename, "r") as ds:
        attrs = {key: ds.getncattr(key) for key in ds.ncattrs() if is_provenance_attr(key)}
    return stamp_from_attrs(attrs)


def _inside(product: Path) -> Stamp | None:
    """The stamp a product carries in its own attributes, or ``None`` when it carries none or
    cannot be opened as netCDF (an empty test fixture, a product still being written)."""
    if not product.is_file() or product.stat().st_size == 0:
        return None
    try:
        return read_in_file_stamp(product)
    except (OSError, RuntimeError, ValueError):
        return None
