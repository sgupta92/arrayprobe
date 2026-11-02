# SPDX-License-Identifier: BSD-3-Clause
"""The author-editable defaults file -- minimal form.

Scope (project decision, 2026-09-28): *"Minimal
version: base profile plus the six reject thresholds, name carrying a content hash, stamp
``authordefaults:<path>#<sha>``, reached by ``[fidelity].authordefaults``."* This module is
that minimal form and nothing more; every wider reading floated in the archived planning notes
(option B:
a free-form threshold/correction file) is explicitly **not** built here -- the agreed
scope is one axis.

**Why this does not break the no-raw-thresholds rule** (``config.py``: a config file may
*select* a documented behaviour, never *describe* one). This file does not talk to the port.
It is TOML *input to a generator*, exactly the shape option B always was: the six
:class:`~arrayprobe_uiops.reject_core.RejectConfig` fields it may set are assembled in Python into a
full, fully-specified :class:`~arrayprobe.profiles.FidelityProfile` and handed to
:func:`arrayprobe.profiles.register_profile`, which enforces the same completeness and
uniqueness rules a fork's own hand-written registration would. The six reject thresholds are
the one axis :func:`arrayprobe.config.load_config` already exempts from that rule in part
(``[thresholds].area_ratio_z``/``default_int_arr_thresh``) -- this file is the same
kind of lift, generalised to the reject-config axis and routed through registration rather
than through a raw config key, because these six are ``FidelityProfile`` fields, not
``sizeDist`` call arguments.

Every override carries a **citation** -- who chose the value and why -- refused if missing,
because a threshold with no author behind it is indistinguishable from a guess (the project's
"never invent a fact" rule, applied to a number instead of a literature claim).

**The file name carries a content hash** (``authordefaults-<sha256 prefix>.toml``) so an edit
without a rename is caught rather than silently changing what a run reproduces -- the same
"a check must draw its two sides from different places" shape as every other guard in this
project: the name is a claim, the bytes are the fact, and :func:`load_authordefaults` refuses
to run when they disagree.

Absent ``[fidelity].authordefaults``, none of this runs: :mod:`arrayprobe.config` behaves
exactly as it did before this module existed (``tests/test_authordefaults.py``).
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from . import profiles
from .profiles import FidelityProfile

__all__ = [
    "THRESHOLD_KEYS",
    "AuthorDefaultsError",
    "AuthorDefaults",
    "content_hash",
    "expected_filename",
    "load_authordefaults",
    "resolve_profile",
]


class AuthorDefaultsError(ValueError):
    """An ``authordefaults*.toml`` file that cannot be trusted as written."""


#: The six thresholds ``calculate_reject_unified.m:71-77`` assigns -- every field of
#: :class:`arrayprobe_uiops.reject_core.RejectConfig` -- and the only ones this file may override.
#: Every
#: other :class:`~arrayprobe.profiles.FidelityProfile` field stays a Python registration
#: (the same rule): those name a divergence between two MATLAB *trees*, not a per-run choice.
THRESHOLD_KEYS: frozenset[str] = frozenset(
    {"rej_zero_area", "rej_split", "rej_hollow", "shadowed_area", "max_edge_img_ar",
     "max_comp_img_ar"}
)

#: rej_zero_area/rej_split/rej_hollow are booleans on RejectConfig; the other three are
#: numeric (float, though the shipped defaults are written as plain ints in Python).
_BOOL_KEYS = frozenset({"rej_zero_area", "rej_split", "rej_hollow"})

_HASH_LEN = 16  # hex chars: 64 bits, ample to catch an accidental collision, short in a filename
_NAME_RE = re.compile(rf"^authordefaults-([0-9a-f]{{{_HASH_LEN}}})\.toml$")


def _resolve_base_profile_name(name: str) -> str | None:
    """A base-profile name as ``load_authordefaults`` accepts it -- either spelling.

    ``arrayprobe.config`` builds the CONSTANT-style alias table (``STOCK_V314`` for
    ``stock-v3.1.4``) from :data:`arrayprobe.profiles.SHIPPED` the same way; it is not
    imported from there because ``config.py`` imports this module, and reusing the same
    one-line transform here is simpler than restructuring either module to avoid the cycle.
    Returns the canonical (hyphenated) registry key, or ``None`` if ``name`` is neither.
    """
    if name in profiles.PROFILES:
        return name
    alias = name.upper().replace("-", "_").replace(".", "")
    table = {n.upper().replace("-", "_").replace(".", ""): n for n in profiles.SHIPPED}
    return table.get(alias)


def content_hash(data: bytes) -> str:
    """The filename's hash segment: the first 16 hex chars of the file's own SHA-256."""
    return hashlib.sha256(data).hexdigest()[:_HASH_LEN]


def expected_filename(data: bytes) -> str:
    """What this file's name must be, given its bytes."""
    return f"authordefaults-{content_hash(data)}.toml"


@dataclass(frozen=True)
class AuthorDefaults:
    """One validated ``authordefaults*.toml`` file: a base profile plus cited overrides."""

    path: Path
    hash: str
    base_profile_name: str
    overrides: dict[str, bool | float]
    citations: dict[str, str]

    def stamp(self) -> str:
        """The ``.call`` sidecar fragment: ``authordefaults:<path>#<sha>``."""
        return f"authordefaults:{self.path}#{self.hash}"


def load_authordefaults(path) -> AuthorDefaults:
    """Read and validate an author-editable defaults file.

    Raises :class:`AuthorDefaultsError` for anything that would let the file describe a
    threshold without a citation, name a key that is not one of the six, or run under a
    name that does not match its own content.
    """
    path = Path(path)
    if path.is_dir():
        raise AuthorDefaultsError(f"{path} is a directory; name the .toml file inside it")
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise
    if not _NAME_RE.match(path.name):
        expected = expected_filename(data)
        raise AuthorDefaultsError(
            f"{path.name!r} is not a valid author-defaults file name (expected "
            f"authordefaults-<16 hex chars>.toml, e.g. {expected!r} for this file's current "
            "content) -- the name carries a content hash so an edit without a rename is caught "
            "rather than silently changing what a run reproduces"
        )
    expected = expected_filename(data)
    if path.name != expected:
        raise AuthorDefaultsError(
            f"{path.name} does not match its own content: expected {expected!r}. Rename the "
            "file (or regenerate it) after any edit -- the mismatch is the whole point of the "
            "hash: a file that could drift from its name silently could change a run's reject "
            "thresholds with no record that it happened."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AuthorDefaultsError(f"{path} is not UTF-8: {exc}") from exc
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise AuthorDefaultsError(f"{path} is not valid TOML: {exc}") from exc

    unknown_sections = sorted(set(doc) - {"fidelity", "thresholds"})
    if unknown_sections:
        raise AuthorDefaultsError(
            f"unknown section(s) {unknown_sections} in {path}; an author-defaults file may hold "
            "only [fidelity] (base_profile) and [thresholds] (the six reject thresholds)"
        )

    fid = doc.get("fidelity")
    if not isinstance(fid, dict) or "base_profile" not in fid:
        raise AuthorDefaultsError(
            f"{path}: [fidelity].base_profile is required -- no base profile is ever assumed"
        )
    extra_fid = sorted(set(fid) - {"base_profile"})
    if extra_fid:
        raise AuthorDefaultsError(
            f"[fidelity] has unknown key(s) {extra_fid} in {path}; known: ['base_profile']"
        )
    given_base_name = fid["base_profile"]
    base_name = _resolve_base_profile_name(given_base_name) if isinstance(given_base_name, str) \
        else None
    if base_name is None:
        known = sorted(profiles.PROFILES)
        raise AuthorDefaultsError(
            f"unknown base profile {given_base_name!r} in {path}; known: {known}"
        )

    thresholds = doc.get("thresholds", {})
    if not isinstance(thresholds, dict):
        raise AuthorDefaultsError(
            f"[thresholds] in {path} must be a table of <threshold name> = "
            "{value = ..., citation = \"...\"}"
        )
    unknown_thresholds = sorted(set(thresholds) - THRESHOLD_KEYS)
    if unknown_thresholds:
        verb = "is" if len(unknown_thresholds) == 1 else "are"
        raise AuthorDefaultsError(
            f"[thresholds] names {unknown_thresholds} in {path}, which {verb} not one of the "
            f"six reject thresholds this file may override: {sorted(THRESHOLD_KEYS)}. Every "
            "other FidelityProfile field is a scientific claim registered in Python "
            "(register_profile()), never described in a config file: thresholds are never set "
            "in a config file, only selected."
        )

    overrides: dict[str, bool | float] = {}
    citations: dict[str, str] = {}
    for key, entry in thresholds.items():
        if not isinstance(entry, dict) or set(entry) != {"value", "citation"}:
            got = sorted(entry) if isinstance(entry, dict) else entry
            raise AuthorDefaultsError(
                f"[thresholds.{key}] in {path} must be a table with exactly 'value' and "
                f"'citation' keys, got {got!r}"
            )
        citation = entry["citation"]
        if not isinstance(citation, str) or not citation.strip():
            raise AuthorDefaultsError(
                f"[thresholds.{key}] in {path} has no citation -- who chose this value and why "
                "is required for every override, never left implicit"
            )
        value = entry["value"]
        if key in _BOOL_KEYS:
            if not isinstance(value, bool):
                raise AuthorDefaultsError(
                    f"[thresholds.{key}].value in {path} must be true or false, got {value!r}"
                )
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise AuthorDefaultsError(
                    f"[thresholds.{key}].value in {path} must be a number, got {value!r}"
                )
        overrides[key] = value
        citations[key] = citation

    return AuthorDefaults(
        path=path,
        hash=content_hash(data),
        base_profile_name=base_name,
        overrides=overrides,
        citations=citations,
    )


def resolve_profile(defaults: AuthorDefaults) -> FidelityProfile:
    """Build (and register, once per interpreter) the profile this file selects.

    The name is derived from the file's own content hash (``authordefaults-<hash>``), so a
    config loaded twice in one process -- or by a ``--jobs``/``--chunks`` worker that has
    never seen this file before -- resolves to the same registration rather than raising on
    the second call: idempotent by construction, the same property
    ``[fidelity].profile_module`` relies on for a fork's own registered variant.
    """
    base = profiles.PROFILES[defaults.base_profile_name]
    name = f"authordefaults-{defaults.hash}"
    if name in profiles.PROFILES:
        return profiles.PROFILES[name]
    # mypy cannot check a **dict against mixed-type fields; load_authordefaults validated it.
    reject = replace(base.reject_thresholds, **defaults.overrides)  # type: ignore[arg-type]
    description = (
        f"Author-editable defaults ({defaults.path.name}), base {base.name}: "
        + "; ".join(f"{k}={v} ({defaults.citations[k]})" for k, v in defaults.overrides.items())
        if defaults.overrides
        else f"Author-editable defaults ({defaults.path.name}), base {base.name}: no overrides"
    )
    new = replace(base, name=name, description=description, reject_thresholds=reject)
    cites_tree = "3.5" if base.name in profiles._V35_TREE_PROFILES else "3.1.4"
    return profiles.register_profile(new, cites_tree=cites_tree)
