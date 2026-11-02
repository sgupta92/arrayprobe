# SPDX-License-Identifier: BSD-3-Clause
"""Every opt-in is mentioned in an example notebook (the author's standing rule).

WHAT THIS PROTECTS. Author, 2026-09-14, verbatim: *"add a parameter, default off with option
to turn on - mentioned in example notebooks (this goes for all opt ins)"*. Until this module
nothing checked the second half: an opt-in could ship, tested in both states as the fidelity
doctrine requires, and still be invisible to a reader of ``examples/`` -- the one place a
new user learns what the package can be told to do.

WHAT COUNTS AS AN OPT-IN, decided here and derived from the code, never from a document:

1. **``enhancement``** -- every name in ``arrayprobe_enhancements.registry.REGISTRY``. Each
   is OFF in the port (``RunConfig.enabled`` returns ``False`` unless ``[enhancements]``
   names it ``true``) and ON in the enhancements package, so it is an opt-in in the pipeline
   that reproduces UIOOPS and an opt-out in the one that corrects it; a notebook naming it
   covers both.
2. **``soda2-enhancement``** -- every name in ``arrayprobe_soda2_enhancements.registry.REGISTRY``
   (same two-default shape, the SODA-2 lineage). Registration is an import-time side effect
   of each correction module, so every module is imported before the registry is read.
3. **``cli-flag``** -- every ``add_argument`` in ``arrayprobe``'s CLI
   (``src/arrayprobe/cli.py``) and in ``scripts/run_flight.py`` that is ``action="store_true"``
   (off unless given) or is an ``int`` defaulting to ``1`` (the serial default of a speed flag:
   ``--jobs``, ``--s2-jobs``, ``--chunks`` -- pinned below against that documented set, so the
   rule cannot silently widen or narrow). Read from the source's AST, because
   ``run_flight.py`` builds its parser inline in ``main`` and has no builder to call.
4. **``keyword``** -- every keyword parameter defaulting to ``False`` on a public function or
   public-class method of the four port packages (``arrayprobe``, ``arrayprobe_uiops``,
   ``arrayprobe_soda2``, ``uiops``), outside ``_private`` modules. This includes keywords
   that mirror a MATLAB/IDL argument of the same name; whether those are "opt-ins" in the
   author's sense is not decided here -- they sit in ``PENDING`` until a notebook names them
   or the author rules them out.
5. **``config-key``** -- every key ``arrayprobe.config.load_config`` reads with a ``False``
   default (``table.get("k", False)`` / ``table.pop("k", False)``), i.e. ``[combine].borrowed``.
6. **``profile-field``** -- a ``FidelityProfile`` field with a ``False`` default. There are
   none: every field is required, because no profile is ever defaulted
   (``test_profile_is_never_defaulted.py``). Derived all the same, so the day one gains a
   default it is inventoried here without anyone remembering to add it.

**Not inventoried** (and why): a ``FidelityProfile`` *name* is a required choice, not a
default-off switch; non-boolean choices with a non-``False`` default (``[export].format``,
``--engine``, ``--preset``) select among alternatives rather than turning something on.

WHAT COUNTS AS A MENTION. The opt-in's literal token in the *source* of a cell (code or
markdown) of an ``examples/*.ipynb`` -- never in its outputs, because an output printed by
iterating the registry would be the registry quoting itself, and a check must draw its two
sides from different places. Tokens: an enhancement's name; a flag's option string
(``--s2-jobs``); a keyword as ``name=``; a config key as its ``[table]`` and ``key`` in the
same cell.

THE RATCHET. ``PENDING`` lists the opt-ins that no notebook named when this was written, so
the test passes today and any *new* opt-in without a mention fails. It only shrinks:
``test_pending_entries_are_still_unmentioned`` fails when a notebook starts naming one, so
the entry is removed rather than left to excuse a future regression.

THIS GUARD IS EXECUTED, NOT READ: ``test_the_check_fires_*`` delete a mention from an
in-memory copy of the notebooks, and add an unregistered opt-in, and assert both are reported.
"""
from __future__ import annotations

import ast
import copy
import dataclasses
import importlib
import importlib.util
import json
import pkgutil
import re
import sys
import unittest
from pathlib import Path
from typing import Any

from tests._repo import PKG_ROOT, needs_enhancements, repo_only  # noqa: E402

_V314_ABSENT = importlib.util.find_spec("arrayprobe.reject") is None

REPO_ROOT = Path(__file__).resolve().parents[1]
PORT_ROOT = PKG_ROOT
EXAMPLES = REPO_ROOT / "examples"
SRC = PORT_ROOT / "src"
# The driver lives in arrayprobe.driver (moved from scripts/ on 2026-10-01); `scripts/run_flight.py`
# is a shim with no add_argument calls, so scanning it alone would silently check nothing.
CLI_SOURCES = tuple(p for p in (SRC / "arrayprobe" / "cli.py",
                               SRC / "arrayprobe" / "driver" / "run_flight.py",
                               SRC / "arrayprobe" / "run_flight.py",
                               PORT_ROOT / "scripts" / "run_flight.py") if p.exists())

#: int-typed flags defaulting to 1 that are NOT speed switches: positions or counts a
#: user supplies, never an opt-in. Each named with its reason.
NOT_SPEED_FLAGS = {
    "--record": "`arrayprobe view strip`: the first record to draw, 1-based (A14)",
}
PORT_PACKAGES = ("arrayprobe", "arrayprobe_uiops", "arrayprobe_soda2", "uiops")
SODA2_ENH_SRC = REPO_ROOT / "enhancements_soda2" / "src"

#: The speed flags the package documentation names ("``--s2-jobs``, ``--chunks``, ``--jobs``, all
#: defaulting to serial"), plus ``--enh-jobs`` (the enhancement pass's worker count,
#: serial by default; 08_opt_ins section 4). Typed here on purpose: it is the second side
#: the int-default-1 rule in :func:`_cli_flags` is checked against.
DOCUMENTED_SPEED_FLAGS = {"--jobs", "--s2-jobs", "--chunks", "--enh-jobs"}


@dataclasses.dataclass(frozen=True)
class OptIn:
    kind: str
    name: str
    where: str

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.name}"

    def tokens(self) -> tuple[str, ...]:
        """Literal strings that must all appear in one notebook cell's source to count."""
        if self.kind == "keyword" or self.kind == "profile-field":
            return (f"{self.name}=",)
        if self.kind == "config-key":
            table, key = self.name.split(".", 1)
            return (table, key)
        if self.kind == "enhancement":
            # "analysis" is also an English word: require the package context in the cell.
            return (self.name, "enhancements")
        if self.kind == "soda2-enhancement":
            return (self.name, "soda2")
        return (self.name,)

    def patterns(self) -> tuple[re.Pattern, ...]:
        """:meth:`tokens` as regexes. The opt-in's own token is bounded -- ``--jobs`` must not
        match inside ``--s2-jobs``, ``crop=`` not inside ``no_crop=``, ``plot=`` not inside
        ``plot==``; a context token (``enhancements``, ``soda2``) is a plain substring, so
        ``arrayprobe_soda2_enhancements`` supplies it."""
        first, *context = self.tokens()
        tail = r"(?!=)" if first.endswith("=") else r"(?![\w-])"
        return (re.compile(r"(?<![\w-])" + re.escape(first) + tail),
                *(re.compile(re.escape(t)) for t in context))

    def table_patterns(self) -> tuple[re.Pattern, ...] | None:
        """The second way an enhancement is presented as an opt-in: as a key of the run
        configuration's ``[enhancements]`` table, in a cell that builds that table's string.

        08_opt_ins splits each table across cells, so a continuation cell such as
        ``ENHANCEMENTS_TABLE += \"\"\"int16_double_fix = false ...`` carries neither the
        lowercase ``enhancements`` nor (for SODA-2) ``soda2`` that :meth:`patterns` keys on.
        The context is NOT made case-insensitive: that would let prose such as "Enhancements
        change the analysis" mention ``analysis``. Instead both sides are exact: the name as a
        whole TOML line ``<name> = true|false``, and an assignment to the table's own variable
        -- ``ENHANCEMENTS_TABLE`` for UIOOPS, ``SODA2_ENHANCEMENTS_TABLE`` for SODA-2, each
        bounded so neither matches inside the other. A name merely printed beside the variable,
        or a UIOOPS name in the SODA-2 table, does not count."""
        table_var = {"enhancement": "ENHANCEMENTS_TABLE",
                     "soda2-enhancement": "SODA2_ENHANCEMENTS_TABLE"}.get(self.kind)
        if table_var is None:
            return None
        # A key line starts the line or the string literal (`+= """int16_double_fix = false`).
        key = (r'(?m)(?:^|""")[ \t]*' + re.escape(self.name)
               + r"[ \t]*=[ \t]*(true|false)[ \t]*$")
        return (re.compile(key), re.compile(r"(?<!\w)" + table_var + r"[ \t]*\+?="))


# --------------------------------------------------------------------------- inventory

def _enhancements() -> list[OptIn]:
    from arrayprobe_enhancements.registry import REGISTRY
    return [OptIn("enhancement", n, "arrayprobe_enhancements.registry") for n in REGISTRY]


def _soda2_enhancements() -> list[OptIn]:
    """Read from the repository's source tree, then leave ``sys.path``/``sys.modules`` as found:
    the package is not installed in the shared venv, and ``test_cli_soda2`` covers both states."""
    saved_path = list(sys.path)
    before = {m for m in sys.modules if m.startswith("arrayprobe_soda2_enhancements")}
    try:
        if str(SODA2_ENH_SRC) not in sys.path:
            sys.path.insert(0, str(SODA2_ENH_SRC))
        pkg = importlib.import_module("arrayprobe_soda2_enhancements")
        for mod in pkgutil.iter_modules(pkg.__path__):
            if mod.name != "registry" and not mod.name.startswith("_"):
                importlib.import_module(f"arrayprobe_soda2_enhancements.{mod.name}")
        registry = importlib.import_module("arrayprobe_soda2_enhancements.registry")
        return [OptIn("soda2-enhancement", n, "arrayprobe_soda2_enhancements.registry")
                for n in registry.REGISTRY]
    finally:
        sys.path[:] = saved_path
        for m in [m for m in sys.modules
                  if m.startswith("arrayprobe_soda2_enhancements") and m not in before]:
            del sys.modules[m]


def _kw(call: ast.Call, name: str):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def cli_flags_in(source: str, where: str) -> list[OptIn]:
    """Every default-off flag an ``add_argument`` call in ``source`` declares."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            continue
        options = [a.value for a in node.args
                   if isinstance(a, ast.Constant) and isinstance(a.value, str)
                   and a.value.startswith("--")]
        if not options:
            continue
        # A flag hidden with help=argparse.SUPPRESS is internal plumbing the driver passes to its
        # own workers (e.g. --_protective-worker), not something a user turns on.
        help_kw = _kw(node, "help")
        if isinstance(help_kw, ast.Attribute) and help_kw.attr == "SUPPRESS":
            continue
        # A flag whose help is SUPPRESS in one branch of a conditional is hidden when the v3.1.4
        # engine is absent; its notebook mention lives in a v3.1.4-only cell that tree drops.
        if (isinstance(help_kw, ast.IfExp) and _V314_ABSENT
                and any(isinstance(b, ast.Attribute) and b.attr == "SUPPRESS"
                        for b in (help_kw.body, help_kw.orelse))):
            continue
        action, typ, default = _kw(node, "action"), _kw(node, "type"), _kw(node, "default")
        store_true = isinstance(action, ast.Constant) and action.value == "store_true"
        serial = (isinstance(typ, ast.Name) and typ.id == "int"
                  and isinstance(default, ast.Constant) and default.value == 1
                  and node.args and getattr(node.args[0], "value", None) not in NOT_SPEED_FLAGS)
        if store_true or serial:
            found.append(OptIn("cli-flag", options[0], where))
    return found


def _cli_flags() -> list[OptIn]:
    out: dict[str, OptIn] = {}
    for path in CLI_SOURCES:
        rel = path.relative_to(REPO_ROOT).as_posix()
        for o in cli_flags_in(path.read_text(encoding="utf-8"), rel):
            out.setdefault(o.name, o)
    return list(out.values())


def keywords_in(source: str, where: str) -> list[OptIn]:
    """Keyword parameters defaulting to ``False`` on public functions / public-class methods."""
    found = []
    tree = ast.parse(source)
    funcs = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            funcs.append((node.name, node))
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            funcs += [(f"{node.name}.{m.name}", m) for m in node.body
                      if isinstance(m, ast.FunctionDef)]
    for qual, fn in funcs:
        if fn.name.startswith("_") and fn.name != "__init__":
            continue
        a = fn.args
        positional = a.posonlyargs + a.args
        defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
        # Equal lengths by construction (ast pads kw_defaults with None), hence strict.
        for arg, d in [*zip(positional, defaults, strict=True),
                       *zip(a.kwonlyargs, a.kw_defaults, strict=True)]:
            if isinstance(d, ast.Constant) and d.value is False:
                found.append(OptIn("keyword", arg.arg, f"{where}:{qual}"))
    return found


def _keywords() -> list[OptIn]:
    out: dict[str, OptIn] = {}
    for pkg in PORT_PACKAGES:
        for path in sorted((SRC / pkg).rglob("*.py")):
            rel = path.relative_to(SRC)
            if any(p.startswith("_") and p != "__init__.py" for p in rel.parts):
                continue
            for o in keywords_in(path.read_text(encoding="utf-8"), rel.as_posix()):
                out.setdefault(o.name, o)
    return list(out.values())


def _config_keys() -> list[OptIn]:
    """``[table].key`` for every ``<table>.get/pop("key", False)`` in ``load_config``."""
    path = SRC / "arrayprobe" / "config.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    load = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "load_config")
    # which table each local was read from: `comb = dict(doc.get("combine", {}))`
    table_of: dict[str, str] = {}
    for node in ast.walk(load):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            for sub in ast.walk(node.value):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "get" and isinstance(sub.func.value, ast.Name)
                        and sub.func.value.id == "doc" and sub.args
                        and isinstance(sub.args[0], ast.Constant)):
                    table_of[node.targets[0].id] = sub.args[0].value
    found = []
    for node in ast.walk(load):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("get", "pop") and len(node.args) == 2
                and isinstance(node.args[1], ast.Constant) and node.args[1].value is False
                and isinstance(node.func.value, ast.Name)):
            table = table_of.get(node.func.value.id, node.func.value.id)
            found.append(OptIn("config-key", f"[{table}].{node.args[0].value}",
                               "src/arrayprobe/config.py:load_config"))
    return found


def _profile_fields() -> list[OptIn]:
    from arrayprobe.profiles import FidelityProfile
    return [OptIn("profile-field", f.name, "arrayprobe.profiles.FidelityProfile")
            for f in dataclasses.fields(FidelityProfile) if f.default is False]


def inventory() -> list[OptIn]:
    return sorted([*_enhancements(), *_soda2_enhancements(), *_cli_flags(), *_keywords(),
                   *_config_keys(), *_profile_fields()], key=lambda o: o.key)


# --------------------------------------------------------------------------- mentions

def _notebooks() -> list[Path]:
    return (
        sorted(p for p in EXAMPLES.rglob("*.ipynb") if ".ipynb_checkpoints" not in p.parts)
        if EXAMPLES.is_dir() else []
    )


def load_cells() -> dict[str, list[str]]:
    """Notebook name -> the source of each of its cells (code and markdown; never outputs)."""
    return {p.relative_to(EXAMPLES).as_posix(): ["".join(c.get("source", []))
                     for c in json.loads(p.read_text(encoding="utf-8"))["cells"]]
            for p in _notebooks()}


def _mentions(opt: OptIn, src: str) -> bool:
    if all(p.search(src) for p in opt.patterns()):
        return True
    table = opt.table_patterns()
    return table is not None and all(p.search(src) for p in table)


def mentioned_in(opt: OptIn, cells: dict[str, list[str]]) -> list[str]:
    return [nb for nb, sources in cells.items() if any(_mentions(opt, src) for src in sources)]


def unmentioned(opts: list[OptIn], cells: dict[str, list[str]]) -> list[str]:
    return [o.key for o in opts if not mentioned_in(o, cells)]


# --------------------------------------------------------------------------- the ratchet
#
# Opt-ins no example notebook names. Measured 2026-09-14: 86 of 88 before
# examples/2_processing/08_opt_ins.ipynb, none after it, so the list starts empty. It exists for
# the day a
# merge brings an opt-in whose mention another lane owns: add it here with that owner, and
# test_pending_entries_are_still_unmentioned makes sure it comes out again. Never add one to
# excuse an opt-in nobody is writing a mention for.
#: The driver stages' Python keywords, each the signature of a driver flag examples/08_opt_ins
#: already shows; inventoried since the driver moved from scripts/ into arrayprobe.driver.
_DRIVER_KEYWORD = ("in arrayprobe.driver.run_flight: the keyword behind a driver flag that "
                   "08_opt_ins shows as the flag; inventoried since the driver moved into "
                   "the package (2026-10-01); owned by a markdown cell in 08_opt_ins naming "
                   "each keyword beside its flag, queued with the notebook work of "
                   "2026-10-01 (figures, xarray, the microphysics notebook).")
V314_ENGINE_ONLY_PENDING = frozenset({"keyword:write_provenance"})
#: Entries whose subject is arrayprobe.tools.nasa_ames_tas, the NASA-Ames TAS reader the public
#: release holds back (it stays in the development repository); excused only where it is absent.
NASA_AMES_ONLY_PENDING = frozenset({"keyword:round_seconds", "keyword:drop_missing"})

PENDING: dict[str, str] = {
    "cli-flag:--json": "arrayprobe tune settings --json (the table with every source line) and "
                       "arrayprobe tune diodes --json (the stuck-diode report); owned by the "
                       "tuning-loop notebook queued with the notebook work of 2026-10-01 "
                       "(figures, xarray, the microphysics notebook).",
    "cli-flag:--round-seconds": "tas-from-nasa-ames, for a 1 Hz aircraft file whose grid is "
                                "offset from the whole second -- UND's own .basic.1Hz sits "
                                "0.21 s off (2026-09-22). No notebook builds a TAS "
                                "sidecar from a NASA-Ames file, so nothing demonstrates it.",
    "keyword:round_seconds": "the same choice on nasa_ames_tas.tas_series; covered by "
                             "tests/test_nasa_ames_tas_choices.py, not by a notebook.",
    "keyword:drop_missing": "nasa_ames_tas.tas_series(drop_missing=True); its 08_opt_ins row "
                            "was removed so the notebook does not import the NASA-Ames reader "
                            "the public release holds back; covered by "
                            "tests/test_nasa_ames_tas_choices.py.",
    "cli-flag:--attributed": "scripts/run_flight.py's self-describing sibling output ("
                             "attributed_export.export); no example notebook runs the "
                             "one-command driver CLI, so nothing yet demonstrates it.",
    "cli-flag:--require": "arrayprobe cli's `provenance` subcommand (provenance "
                          "work, 2026-09-18); no notebook demonstrates the provenance CLI.",
    "keyword:primed": "arrayprobe_uiops.imgproc.merge_chunks_v35's prefix-priming plumbing "
                      "(2026-09-18); exercised by tests/test_v35_sizedist_chunk_priming.py "
                      "and tests/test_run_flight_chunk_priming.py, not yet by a notebook.",
    "keyword:require": "arrayprobe.provenance.report(require=...) (provenance work, 2026-09-18); "
                       "no notebook demonstrates the provenance report path yet.",
    "keyword:write_provenance": "arrayprobe.imgproc.imgproc_sm(write_provenance=...) netCDF "
                                "provenance attributes (2026-09-18), default OFF; no "
                                "notebook demonstrates it yet.",
    "keyword:allow_mixed": f"stage_combine(allow_mixed=...) {_DRIVER_KEYWORD}",
    "keyword:attributed": f"stage_combine(attributed=...) {_DRIVER_KEYWORD}",
    "keyword:borrowed": f"stage_combine(borrowed=...) {_DRIVER_KEYWORD}",
    "keyword:diode_corrected": f"stage_combine(diode_corrected=...) {_DRIVER_KEYWORD}",
    "keyword:resume_chunks": f"stage3(resume_chunks=...) {_DRIVER_KEYWORD}",
}


#: Present in the development repository, absent from a release tree (it does not ship).
ALLOWLIST = REPO_ROOT / "scripts" / "release_allowlist.txt"

#: Spot checks typed here, the second side of the derived inventory.
KNOWN_OPT_INS = ("cli-flag:--s2-jobs", "cli-flag:--chunks", "cli-flag:--jobs",
                 "cli-flag:--borrowed-combine", "cli-flag:--accept-unstamped",
                 "config-key:[combine].borrowed", "keyword:fix_b8",
                 "keyword:warn_on_cap", "enhancement:wide_hollow_fix",
                 "enhancement:spot_edge_fix")


def _known_opt_ins_missing(keys: set[str], omitted: set[str]) -> list[str]:
    """Spot checks absent from ``keys``. An ``enhancement:`` whose name is in ``omitted`` (the
    registry's ``OMITTED``: v3.1.4-only modules a release tree does not ship) is excused, and
    must then be absent; no other name is excused."""
    missing = []
    for expected in KNOWN_OPT_INS:
        kind, name = expected.split(":", 1)
        if kind == "enhancement" and name in omitted:
            if expected in keys:
                missing.append(f"{expected} (omitted, yet inventoried)")
        elif expected not in keys:
            missing.append(expected)
    return missing


# The inventory reads the repository's notebooks and enhancements_soda2/ source, and
# imports arrayprobe_enhancements; none of them travels in the sdist.
@repo_only
@needs_enhancements
class EveryOptInIsInANotebook(unittest.TestCase):

    cells: Any  # assigned in setUpClass/setUp; see there for the value
    opts: Any  # assigned in setUpClass/setUp; see there for the value
    @classmethod
    def setUpClass(cls) -> None:
        cls.opts = inventory()
        cls.cells = load_cells()

    def test_notebooks_and_inventory_are_non_empty(self) -> None:
        """The empty-glob failure this project keeps finding, guarded for both sides."""
        self.assertTrue(self.cells, f"no *.ipynb under {EXAMPLES}")
        kinds = {o.kind for o in self.opts}
        for kind in ("enhancement", "soda2-enhancement", "cli-flag", "keyword", "config-key"):
            self.assertIn(kind, kinds, f"the {kind} inventory came back empty")

    def test_the_driver_flags_are_scanned(self) -> None:
        """Wherever the driver lives, its --preset flag must be in the scanned sources --
        else a move (like R65's into src/) leaves this guard checking nothing."""
        self.assertTrue(any('"--preset"' in p.read_text(encoding="utf-8") for p in CLI_SOURCES),
                        f"no scanned CLI source declares --preset: {CLI_SOURCES}")

    def test_the_int_default_1_rule_finds_exactly_the_documented_speed_flags(self) -> None:
        serial = set()
        for path in CLI_SOURCES:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "add_argument"):
                    typ, default = _kw(node, "type"), _kw(node, "default")
                    if (isinstance(typ, ast.Name) and typ.id == "int"
                            and isinstance(default, ast.Constant) and default.value == 1
                            and node.args[0].value not in NOT_SPEED_FLAGS):
                        serial.add(node.args[0].value)
        self.assertEqual(DOCUMENTED_SPEED_FLAGS, serial)

    def test_the_known_opt_ins_are_inventoried(self) -> None:
        """Spot checks from outside the derivation: the documented speed flags and config.py.

        ``wide_hollow_fix`` needs the v3.1.4 engine, which the public release does not ship, so
        a release tree's registry holds it in ``OMITTED``. Only a name in ``OMITTED`` is
        excused, and then it must be absent from the inventory; the development view (where
        ``TheDevelopmentViewOmitsNothing`` pins ``OMITTED`` empty) requires every name."""
        from arrayprobe_enhancements import registry
        keys = {o.key for o in self.opts}
        self.assertEqual([], _known_opt_ins_missing(keys, set(registry.OMITTED)))

    def test_an_unknown_spot_check_still_fails_in_either_view(self) -> None:
        """Negative: the excusal covers exactly the omitted names, nothing else."""
        keys = {"cli-flag:--jobs"}
        self.assertIn("enhancement:wide_hollow_fix", _known_opt_ins_missing(keys, set()))
        excused = _known_opt_ins_missing(keys, {"wide_hollow_fix"})
        self.assertNotIn("enhancement:wide_hollow_fix", excused)
        self.assertIn("enhancement:spot_edge_fix", excused)
        self.assertIn("cli-flag:--chunks", excused)
        # An omitted name that still turned up in the inventory is itself a failure.
        self.assertIn("enhancement:wide_hollow_fix (omitted, yet inventoried)",
                      _known_opt_ins_missing(keys | {"enhancement:wide_hollow_fix"},
                                             {"wide_hollow_fix"}))

    def test_every_opt_in_is_mentioned_or_pending(self) -> None:
        missing = [k for k in unmentioned(self.opts, self.cells) if k not in PENDING]
        self.assertEqual(
            [], missing,
            "opt-in(s) no example notebook names (the rule: every opt-in is mentioned in the "
            "example notebooks). Add a cell to examples/2_processing/08_opt_ins.ipynb "
            "showing how to turn "
            "it on, then run scripts/execute_example_notebooks.py 08_opt_ins:\n  "
            + "\n  ".join(missing))

    def test_pending_entries_are_still_unmentioned(self) -> None:
        """The ratchet only shrinks: a PENDING entry a notebook now names must be removed."""
        live = set(unmentioned(self.opts, self.cells))
        # An entry whose subject lives only in the v3.1.4 engine cannot be an opt-in in a
        # tree that does not ship that engine (the public distribution).
        engine_absent = importlib.util.find_spec("arrayprobe.reject") is None
        nasa_ames_absent = importlib.util.find_spec("arrayprobe.tools.nasa_ames_tas") is None
        stale = [k for k in PENDING if k not in live
                 and not (engine_absent and k in V314_ENGINE_ONLY_PENDING)
                 and not (nasa_ames_absent and k in NASA_AMES_ONLY_PENDING)]
        self.assertEqual([], stale, "now mentioned (or no longer an opt-in) -- remove from "
                                    "PENDING:\n  " + "\n  ".join(stale))

    def test_a_suppressed_help_flag_is_not_an_opt_in(self) -> None:
        src = "\n".join([
            "import argparse",
            "ap = argparse.ArgumentParser()",
            'ap.add_argument("--_internal", action="store_true", help=argparse.SUPPRESS)',
            'ap.add_argument("--visible", action="store_true", help="on")',
        ])
        found = [o.name for o in cli_flags_in(src, "x.py")]
        self.assertEqual(found, ["--visible"])

    def test_the_check_fires_when_a_mention_is_deleted(self) -> None:
        """Mutation: strip one mentioned opt-in's token from every cell; it must be reported."""
        target = next(o for o in self.opts if o.kind == "cli-flag" and o.key not in PENDING)
        self.assertNotIn(target.key, unmentioned([target], self.cells), "precondition")
        mutated = copy.deepcopy(self.cells)
        for nb in mutated:
            mutated[nb] = [src.replace(target.tokens()[0], "") for src in mutated[nb]]
        self.assertEqual([target.key], unmentioned([target], mutated))

    def test_the_check_fires_on_a_new_unmentioned_opt_in(self) -> None:
        """Mutation: a new default-off flag and keyword appear in the code; both are caught."""
        flag = cli_flags_in('p.add_argument("--brand-new-thing", action="store_true")', "x")
        kw = keywords_in("def f(a, *, brand_new_switch=False):\n    pass\n", "x")
        self.assertEqual(["cli-flag:--brand-new-thing"], [o.key for o in flag])
        self.assertEqual(["keyword:brand_new_switch"], [o.key for o in kw])
        self.assertEqual(["cli-flag:--brand-new-thing", "keyword:brand_new_switch"],
                         unmentioned(flag + kw, self.cells))

    def test_a_longer_name_does_not_mention_a_shorter_one(self) -> None:
        """``--s2-jobs`` is not a mention of ``--jobs``; ``no_crop=`` is not one of ``crop=``."""
        cells = {"t.ipynb": ["run --s2-jobs 4", "render(no_crop=True)", "if plot==1: pass"]}
        for opt in (OptIn("cli-flag", "--jobs", "x"), OptIn("keyword", "crop", "x"),
                    OptIn("keyword", "plot", "x")):
            self.assertEqual([opt.key], unmentioned([opt], cells))
        self.assertEqual([], unmentioned([OptIn("cli-flag", "--s2-jobs", "x")], cells))

    def test_a_table_continuation_cell_counts_and_a_bare_name_does_not(self) -> None:
        """An ``[enhancements]`` key in a cell building that package's table counts; the name
        with no package context, in prose under a capitalised heading, printed beside the
        table variable, or in the other package's table does not."""
        uiops = OptIn("enhancement", "int16_double_fix", "x")
        word = OptIn("enhancement", "analysis", "x")
        soda2 = OptIn("soda2-enhancement", "aspr_nan_fix", "x")
        table = {"t.ipynb": ['ENHANCEMENTS_TABLE += """int16_double_fix = false\n"""',
                             'SODA2_ENHANCEMENTS_TABLE = """\naspr_nan_fix = false\n"""']}
        self.assertEqual([], unmentioned([uiops, soda2], table))
        cases = {
            "bare name": ["int16_double_fix = false\naspr_nan_fix = false\nanalysis = false"],
            "capitalised prose": ["## Enhancements\nThe analysis below; int16_double_fix too. "
                                  "SODA2 aspr_nan_fix."],
            "printed, not a key": ['ENHANCEMENTS_TABLE = load()\nprint("int16_double_fix", '
                                   '"analysis")', 'SODA2_ENHANCEMENTS_TABLE = x  # aspr_nan_fix'],
            "the other table": ['SODA2_ENHANCEMENTS_TABLE += """int16_double_fix = false\n'
                                'analysis = true\n"""',
                                'ENHANCEMENTS_TABLE = """aspr_nan_fix = false\n"""'],
        }
        for case, sources in cases.items():
            with self.subTest(case=case):
                self.assertEqual([uiops.key, word.key, soda2.key],
                                 unmentioned([uiops, word, soda2], {"t.ipynb": sources}))

    def test_outputs_do_not_count_as_a_mention(self) -> None:
        """A name only in a cell's output is the registry quoting itself, not a mention."""
        opt = OptIn("enhancement", "only_in_an_output", "x")
        nb = {"cells": [{"cell_type": "code", "source": ["print(REGISTRY)"],
                         "outputs": [{"text": ["only_in_an_output\n"]}]}]}
        cells = {"t.ipynb": ["".join(c["source"]) for c in nb["cells"]]}
        self.assertEqual([opt.key], unmentioned([opt], cells))


@needs_enhancements
@unittest.skipUnless(ALLOWLIST.is_file(), "release view: the allow-list does not ship")
class TheDevelopmentViewOmitsNothing(unittest.TestCase):
    """With the allow-list present (development) every module ships, so the ``OMITTED``
    excusal in ``test_the_known_opt_ins_are_inventoried`` cannot fire here."""

    def test_nothing_is_omitted(self) -> None:
        from arrayprobe_enhancements import registry
        self.assertEqual(registry.OMITTED, {})
        self.assertIn("wide_hollow_fix", registry.REGISTRY)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
