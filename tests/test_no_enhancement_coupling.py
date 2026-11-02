# SPDX-License-Identifier: BSD-3-Clause
"""Enforces the one-way dependency between each port and its enhancements package.

Two guards, one visitor: the UIOOPS port ``arrayprobe`` must not import
``arrayprobe_enhancements`` (``enhancements_uiops/``), and the SODA-2 port ``arrayprobe_soda2``
must not
import ``arrayprobe_soda2_enhancements`` (``enhancements_soda2/``). The SODA-2 half was its
own module until 2026-09-29 (author-approved merge; the old module is at
``archive/superseded_tests/test_no_soda2_enhancement_coupling.py``). The classes without a prefix
guard the UIOOPS port; the ``Soda2`` classes guard SODA-2, with the same assertions on their own
root paths.

The UIOOPS half, in the original wording:

User-directed 2026-08-22: real new science (starting with the out-of-focus size
correction) ships as a separate package under
``enhancements_uiops/`` that imports ``arrayprobe``, never the other way round -- that is
what makes it genuinely optional, since deleting ``enhancements_uiops/`` must leave the
port's own build, tests and install untouched.

Refined 2026-08-27: visualization and manual-labeling tooling that never changes a
computed number is core, not enhancement (user-confirmed: "cnn is enhancement, vis
and manual testing is not enhancement"), and `arrayprobe.triage_server` is allowed to
show an optional *suggestion* from an enhancements-side model (the CNN accept/reject
hook, the particle-clustering hook) alongside its own display -- provided that hook
is genuinely optional: wrapped in ``try: ... except ImportError:`` so `arrayprobe`
still imports and runs with `enhancements_uiops/` deleted or uninstalled. That is a
narrower, more precise version of the same rule the original test enforced (which
went dark, silently failing, the moment the first such optional import landed --
exactly the "a rule addressed to attention is not a control" failure mode this
project's own doctrine names). The check below still fails on any *unconditional*
reference to `arrayprobe_enhancements` anywhere in `arrayprobe/`'s source, and it
must keep passing even after `enhancements_uiops/` is deleted, which is why it lives here
rather than there.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src" / "arrayprobe"
_ENHANCEMENTS_ROOT = "arrayprobe_enhancements"
_SODA2_SRC = Path(__file__).resolve().parent.parent / "src" / "arrayprobe_soda2"
_SODA2_ENHANCEMENTS_ROOT = "arrayprobe_soda2_enhancements"


def _is_import_error_handler(handler: ast.ExceptHandler) -> bool:
    """True if this `except` clause catches (Module)ImportError, or is a bare
    `except:` -- the only shapes that make a guarded import genuinely optional."""
    if handler.type is None:
        return True
    names = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(
        isinstance(n, ast.Name) and n.id in ("ImportError", "ModuleNotFoundError") for n in names
    )


class _EnhancementReferenceVisitor(ast.NodeVisitor):
    """Walks a module's AST, flagging any reference to arrayprobe_enhancements
    that is not nested inside a try/except that catches ImportError."""

    def __init__(self, root: str = _ENHANCEMENTS_ROOT) -> None:
        self._root = root
        self._safe_depth = 0
        self.unguarded_linenos: list[int] = []

    def visit_Try(self, node: ast.Try) -> None:
        guarded = any(_is_import_error_handler(h) for h in node.handlers)
        if guarded:
            self._safe_depth += 1
        for child in node.body:
            self.visit(child)
        if guarded:
            self._safe_depth -= 1
        for handler in node.handlers:
            for child in handler.body:
                self.visit(child)
        for child in node.orelse + node.finalbody:
            self.visit(child)

    def _flag(self, node: ast.AST, referenced: bool) -> None:
        if referenced and self._safe_depth == 0:
            self.unguarded_linenos.append(node.lineno)

    def visit_Import(self, node: ast.Import) -> None:
        hit = any(
            a.name == self._root or a.name.startswith(self._root + ".")
            for a in node.names
        )
        self._flag(node, hit)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module
        hit = bool(mod) and (mod == self._root or mod.startswith(self._root + "."))
        self._flag(node, hit)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # A dynamic import (importlib.import_module("arrayprobe_enhancements..."),
        # or the __import__ builtin) is invisible to visit_Import/visit_ImportFrom
        # -- there is no Import/ImportFrom node at all, just a call. Neither is
        # used anywhere in this project today, but the static check should not
        # have a blind spot a future edit could quietly land in.
        callee = node.func
        name = callee.attr if isinstance(callee, ast.Attribute) else (
            callee.id if isinstance(callee, ast.Name) else None
        )
        if name in ("import_module", "__import__"):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    root = self._root
                    hit = arg.value == root or arg.value.startswith(root + ".")
                    self._flag(node, hit)
        self.generic_visit(node)


class VisitorUnitTests(unittest.TestCase):
    """The AST visitor itself, on synthetic snippets -- not real source
    files -- so the dynamic-import detection (added 2026-08-27, a blind
    spot a release-readiness audit found in the original Import/ImportFrom-
    only version) is checked directly rather than only by absence of a hit
    on the real tree, which would also pass if the check were simply broken."""

    def _unguarded(self, src: str) -> list[int]:
        v = _EnhancementReferenceVisitor()
        v.visit(ast.parse(src))
        return v.unguarded_linenos

    def test_plain_import_from_is_flagged(self):
        src = "from arrayprobe_enhancements.foo import bar\n"
        self.assertEqual(self._unguarded(src), [1])

    def test_guarded_import_from_is_not_flagged(self):
        src = (
            "try:\n"
            "    from arrayprobe_enhancements.foo import bar\n"
            "except ImportError:\n"
            "    bar = None\n"
        )
        self.assertEqual(self._unguarded(src), [])

    def test_dynamic_import_module_call_is_flagged(self):
        src = 'importlib.import_module("arrayprobe_enhancements.foo")\n'
        self.assertEqual(self._unguarded(src), [1])

    def test_dynamic_dunder_import_call_is_flagged(self):
        src = '__import__("arrayprobe_enhancements")\n'
        self.assertEqual(self._unguarded(src), [1])

    def test_guarded_dynamic_import_module_call_is_not_flagged(self):
        src = (
            "try:\n"
            '    importlib.import_module("arrayprobe_enhancements.foo")\n'
            "except ImportError:\n"
            "    pass\n"
        )
        self.assertEqual(self._unguarded(src), [])

    def test_unrelated_import_module_call_is_not_flagged(self):
        src = 'importlib.import_module("numpy")\n'
        self.assertEqual(self._unguarded(src), [])

    def test_non_literal_argument_is_not_a_false_positive(self):
        # A dynamic string built at runtime can't be checked statically --
        # confirm this doesn't crash the visitor or spuriously flag it.
        src = "importlib.import_module(some_variable)\n"
        self.assertEqual(self._unguarded(src), [])


class NoEnhancementCouplingTests(unittest.TestCase):
    def test_every_enhancements_reference_is_import_error_guarded(self):
        offenders = []
        for path in _SRC.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if _ENHANCEMENTS_ROOT not in text:
                continue
            visitor = _EnhancementReferenceVisitor()
            visitor.visit(ast.parse(text, filename=str(path)))
            for lineno in visitor.unguarded_linenos:
                offenders.append(f"{path.relative_to(_SRC)}:{lineno}")
        self.assertEqual(
            offenders, [],
            "arrayprobe/ must never require arrayprobe_enhancements -- every reference "
            "must be inside a try/except ImportError so the port still imports and runs "
            f"with enhancements_uiops/ deleted. Unguarded reference(s): {offenders}. "
            "See enhancements_uiops/README.md and triage_server.py's existing CNN-suggestion "
            "hook for the pattern to follow.",
        )

    def test_port_imports_with_enhancements_package_hidden(self):
        """Belt-and-suspenders: actually prove arrayprobe imports clean when
        arrayprobe_enhancements is unimportable, rather than trusting the
        static AST check alone. Runs in a fresh subprocess -- deleting and
        reimporting arrayprobe's submodules in-process was tried first and
        corrupted shared module-level state (the sizing registry, sea's
        decompressor reference) for the rest of the suite; a subprocess is
        also the more faithful analog of the real scenario this guards
        against (enhancements_uiops/ genuinely uninstalled), not a bigger risk."""
        import subprocess
        import sys

        script = (
            "import builtins\n"
            "real_import = builtins.__import__\n"
            "def blocking_import(name, *a, **kw):\n"
            f"    root = {_ENHANCEMENTS_ROOT!r}\n"
            "    if name == root or name.startswith(root + '.'):\n"
            "        raise ImportError(name + ' deliberately hidden for this test')\n"
            "    return real_import(name, *a, **kw)\n"
            "builtins.__import__ = blocking_import\n"
            "import arrayprobe\n"
            "import arrayprobe.triage_server\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=120,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        self.assertEqual(
            result.returncode, 0,
            f"arrayprobe failed to import with arrayprobe_enhancements hidden:\n{result.stderr}",
        )


class Soda2VisitorUnitTests(unittest.TestCase):
    """The AST visitor with the SODA-2 root, on synthetic snippets, mirroring
    ``VisitorUnitTests``."""

    def _unguarded(self, src: str) -> list[int]:
        v = _EnhancementReferenceVisitor(_SODA2_ENHANCEMENTS_ROOT)
        v.visit(ast.parse(src))
        return v.unguarded_linenos

    def test_plain_import_from_is_flagged(self):
        src = "from arrayprobe_soda2_enhancements.foo import bar\n"
        self.assertEqual(self._unguarded(src), [1])

    def test_guarded_import_from_is_not_flagged(self):
        src = (
            "try:\n"
            "    from arrayprobe_soda2_enhancements.foo import bar\n"
            "except ImportError:\n"
            "    bar = None\n"
        )
        self.assertEqual(self._unguarded(src), [])

    def test_dynamic_import_module_call_is_flagged(self):
        src = 'importlib.import_module("arrayprobe_soda2_enhancements.foo")\n'
        self.assertEqual(self._unguarded(src), [1])

    def test_unrelated_import_module_call_is_not_flagged(self):
        src = 'importlib.import_module("numpy")\n'
        self.assertEqual(self._unguarded(src), [])

    def test_the_uiops_root_is_not_the_soda2_root(self):
        # Each guard must fire only on its own package's name.
        src = "from arrayprobe_enhancements.foo import bar\n"
        self.assertEqual(self._unguarded(src), [])


class NoSoda2EnhancementCouplingTests(unittest.TestCase):
    def test_every_enhancements_reference_is_import_error_guarded(self):
        offenders = []
        for path in _SODA2_SRC.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if _SODA2_ENHANCEMENTS_ROOT not in text:
                continue
            visitor = _EnhancementReferenceVisitor(_SODA2_ENHANCEMENTS_ROOT)
            visitor.visit(ast.parse(text, filename=str(path)))
            for lineno in visitor.unguarded_linenos:
                offenders.append(f"{path.relative_to(_SODA2_SRC)}:{lineno}")
        self.assertEqual(
            offenders, [],
            "arrayprobe_soda2/ must never require arrayprobe_soda2_enhancements -- every "
            "reference must be inside a try/except ImportError so the port still imports "
            f"and runs with enhancements_soda2/ deleted. Unguarded reference(s): {offenders}.",
        )


_TOOLS = Path(__file__).resolve().parent.parent / "scripts"


def _top_level_enhancement_imports(src: str) -> list[int]:
    """Lines of module-level (unguarded) imports of either enhancements package.

    A tool may use the enhancements inside a function (imported at the point of use);
    a module-level import makes the tool die at import -- even ``--help`` -- wherever
    the enhancements are not installed (CI run 37125334735).
    """
    roots = (_ENHANCEMENTS_ROOT, _SODA2_ENHANCEMENTS_ROOT)
    lines: list[int] = []
    for node in ast.parse(src).body:
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        if any(n.split(".")[0] in roots for n in names):
            lines.append(node.lineno)
    return lines


class ToolsDoNotImportEnhancementsAtModuleLevel(unittest.TestCase):
    def test_the_sweep_fires_on_a_top_level_import(self):
        self.assertEqual(
            _top_level_enhancement_imports("from arrayprobe_enhancements import registry\n"), [1]
        )
        soda2 = "import arrayprobe_soda2_enhancements.x\n"
        self.assertEqual(_top_level_enhancement_imports(soda2), [1])

    def test_the_sweep_allows_an_import_at_the_point_of_use(self):
        src = "def f():\n    from arrayprobe_enhancements import registry\n    return registry\n"
        self.assertEqual(_top_level_enhancement_imports(src), [])

    def test_no_tool_imports_the_enhancements_at_module_level(self):
        offenders = []
        for path in sorted(_TOOLS.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "enhancements" not in text:
                continue
            for line in _top_level_enhancement_imports(text):
                offenders.append(f"{path.relative_to(_TOOLS.parent)}:{line}")
        self.assertEqual(offenders, [], "import enhancements inside the function using them")


if __name__ == "__main__":
    unittest.main()

# A repository sweep: run before every full suite.
#
PRESUITE_GUARD = True
