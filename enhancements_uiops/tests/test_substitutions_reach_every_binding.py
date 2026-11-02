# SPDX-License-Identifier: BSD-3-Clause
"""Guard: every runtime substitution an enhancement installs reaches every engine binding.

An enhancement that substitutes an engine function at runtime rebinds a *module global*; the
engine's call site then resolves the name in its own module's globals at call time. When a
refactor moves the function and a second engine module starts importing it **by name**, that
module holds its own binding, and a substitution applied to the first module never reaches it.
That is what happened to ``reaccept_every_event_fix`` after the v3.1.4 split (327388c moved
``_reaccept_shattered`` into ``arrayprobe_uiops.sizedist_core``; ``arrayprobe_uiops.sizedist``
imported it by name; v3.5 type 1/2 silently lost the bracket until 8141287).

This test does not list the consumer modules by hand -- a hand-kept list is what drifted. For
each registered substitution it imports every module of the engine packages, finds **every**
module whose globals hold the original function (by identity) at rest, and asserts that inside
the context every one of them resolves to the replacement, and that each named call site still
looks the name up as a global (``LOAD_GLOBAL``) rather than through a local or closure binding.
A new by-name import anywhere in the engines therefore fails here until the context manager
patches it too.

SODA-2's substitutions go through ``arrayprobe_soda2.enhancement_hooks``, which names one
consumer binding per point and is guarded by ``tests/test_soda2_enhancement_hooks.py``
(``pristine`` and a driver run through counting pass-throughs); it is not repeated here.
"""

from __future__ import annotations

import dis
import importlib
import importlib.util
import pkgutil
import sys
import types
import unittest
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable

#: The only registered substitution patches the v3.1.4 engine as well as v3.5; a release tree
#: ships neither that engine nor the enhancement, so the tests that need them skip there.
_V314 = (importlib.util.find_spec("arrayprobe.sizedist") is not None
         and importlib.util.find_spec("arrayprobe_enhancements.reaccept_every_event_fix")
         is not None)
_NO_V314 = ("the v3.1.4 engine and reaccept_every_event_fix, the substitution that patches it, "
            "are not in this release")

#: Engine packages swept for bindings of a substituted function.
ENGINE_PACKAGES = ("arrayprobe", "arrayprobe_uiops")


@dataclass(frozen=True)
class Substitution:
    name: str                       # the enhancement module
    provider: str                   # module defining the original
    attribute: str                  # the global name the call sites resolve
    context: Callable[[], object]   # zero-arg factory returning the context manager
    replacement: Callable[[], object]  # zero-arg getter of the substituted callable
    call_sites: tuple[tuple[str, str], ...]  # (module, function) that must LOAD_GLOBAL it


def _reaccept():
    from arrayprobe_enhancements import reaccept_every_event_fix as m
    return m


#: Every runtime substitution shipped by ``arrayprobe_enhancements`` (swept 2026-10-13:
#: no other enhancement rebinds an engine attribute; the rest are called on arrays).
SUBSTITUTIONS = (
    Substitution(
        name="reaccept_every_event_fix",
        provider="arrayprobe_uiops.sizedist_core",
        attribute="_reaccept_shattered",
        context=lambda: _reaccept().bracketed_reacceptance(True),
        replacement=lambda: _reaccept().bracketed_reaccept_shattered,
        call_sites=(("arrayprobe.sizedist", "_run"),
                    ("arrayprobe_uiops.sizedist", "apply_shattering")),
    ),
)


def _engine_modules() -> list[types.ModuleType]:
    mods = []
    for pkg_name in ENGINE_PACKAGES:
        pkg = importlib.import_module(pkg_name)
        mods.append(pkg)
        for info in pkgutil.walk_packages(pkg.__path__, prefix=pkg_name + "."):
            if ".tests" in info.name or info.name.endswith("__main__"):
                continue
            try:
                mods.append(importlib.import_module(info.name))
            except Exception:  # an optional dependency absent: it cannot bind anything
                continue
    return mods


def bindings_of(fn, modules) -> list[str]:
    """Every module (by name) whose globals hold ``fn`` by identity, under any name."""
    return sorted({m.__name__ for m in modules
                   for v in list(vars(m).values()) if v is fn})


def unreached(sub: Substitution, modules, context=None) -> list[str]:
    """Modules binding the original at rest that do not see the replacement inside ``context``.

    An empty list means the substitution reaches every binding."""
    original = getattr(importlib.import_module(sub.provider), sub.attribute)
    holders = [m for m in modules
               if vars(m).get(sub.attribute) is original and _module_calls(m, sub.attribute)]
    cm = (context or sub.context)()
    with cm:
        repl = sub.replacement()
        return sorted(m.__name__ for m in holders if vars(m).get(sub.attribute) is not repl)


def _module_calls(mod: types.ModuleType, name: str) -> bool:
    """Whether any function or method defined in ``mod`` loads ``name`` as a global.

    A module that binds the name without calling it (the provider that defines it, a
    re-export) has no call site for a substitution to reach."""
    for obj in list(vars(mod).values()):
        if getattr(obj, "__module__", None) != mod.__name__:
            continue
        fns = [obj] if isinstance(obj, types.FunctionType) else (
            [v for v in vars(obj).values() if isinstance(v, types.FunctionType)]
            if isinstance(obj, type) else [])
        if any(_loads_global(f, name) for f in fns):
            return True
    return False


def _loads_global(fn, name: str) -> bool:
    def walk(code):
        for ins in dis.get_instructions(code):
            if ins.opname == "LOAD_GLOBAL" and ins.argval == name:
                return True
        return any(walk(c) for c in code.co_consts if isinstance(c, types.CodeType))
    return walk(fn.__code__)


class EverySubstitutionReachesEveryBinding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = _engine_modules()

    @unittest.skipUnless(_V314, _NO_V314)
    def test_registered_substitutions_reach_every_engine_binding(self):
        for sub in SUBSTITUTIONS:
            with self.subTest(sub.name):
                self.assertEqual(unreached(sub, self.modules), [],
                                 f"{sub.name}: these engine modules bind "
                                 f"{sub.attribute} by name and are not rebound")

    @unittest.skipUnless(_V314, _NO_V314)
    def test_the_named_call_sites_still_bind_the_name_and_resolve_it_at_call_time(self):
        for sub in SUBSTITUTIONS:
            original = getattr(importlib.import_module(sub.provider), sub.attribute)
            for mod_name, fn_name in sub.call_sites:
                with self.subTest(sub=sub.name, site=f"{mod_name}.{fn_name}"):
                    mod = importlib.import_module(mod_name)
                    self.assertIs(vars(mod).get(sub.attribute), original)
                    self.assertTrue(_loads_global(getattr(mod, fn_name), sub.attribute))
                    with sub.context():
                        self.assertIs(vars(mod).get(sub.attribute), sub.replacement())

    def test_every_binding_of_the_original_is_under_the_attribute_name(self):
        # An alias (``from x import _reaccept_shattered as f``) would hide from the rebinding.
        for sub in SUBSTITUTIONS:
            original = getattr(importlib.import_module(sub.provider), sub.attribute)
            with self.subTest(sub.name):
                aliased = sorted({m.__name__ for m in self.modules
                                  for k, v in list(vars(m).items())
                                  if v is original and k != sub.attribute})
                self.assertEqual(aliased, [])

    @unittest.skipUnless(_V314, _NO_V314)
    def test_the_sweep_finds_both_engines(self):
        sub = SUBSTITUTIONS[0]
        original = getattr(importlib.import_module(sub.provider), sub.attribute)
        found = bindings_of(original, self.modules)
        for mod in ("arrayprobe.sizedist", "arrayprobe_uiops.sizedist"):
            self.assertIn(mod, found)


@unittest.skipUnless(_V314, _NO_V314)
class TheGuardFires(unittest.TestCase):
    """The pre-8141287 context (rebinding only ``arrayprobe.sizedist``) is reported."""

    def test_a_context_that_patches_only_the_v314_module_is_reported(self):
        modules = _engine_modules()
        sub = SUBSTITUTIONS[0]
        v314 = sys.modules.get("arrayprobe.sizedist") or importlib.import_module(
            "arrayprobe.sizedist")

        @contextmanager
        def v314_only():
            saved = v314._reaccept_shattered
            v314._reaccept_shattered = sub.replacement()
            try:
                yield
            finally:
                v314._reaccept_shattered = saved

        self.assertEqual(unreached(sub, modules, context=v314_only),
                         ["arrayprobe_uiops.sizedist"])


if __name__ == "__main__":
    unittest.main()
