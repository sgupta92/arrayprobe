# SPDX-License-Identifier: BSD-3-Clause
"""Every third-party module the package imports is declared in ``pyproject.toml``.

``test_dependency_declarations`` checks that the requirements files and the metadata
agree. Neither side of that check is the source code, so a module that starts importing
a new library passes it as long as nobody pins the library anywhere. This test draws its
two sides from the code (an AST walk of every ``src`` module, including imports inside
functions and ``try`` blocks) and from ``pyproject.toml`` (``dependencies`` plus every
optional-dependencies group). A stranger who installs by the metadata then has every
library the code can reach, either in the core or behind a named extra.

An import that is deliberately not declared goes in :data:`ALLOWED_UNDECLARED` with a
reason; an entry the code no longer imports fails, so the allowlist cannot outlive its
subject. No TOML parser: the declaration lines have a fixed shape and are read with a
regular expression, and the parser is asserted to find something before anything is
concluded from it.
"""

from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

from tests._repo import repo_only

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
_PYPROJECT = _ROOT / "pyproject.toml"

#: Import name -> distribution name, where the two differ in more than case.
IMPORT_TO_DISTRIBUTION: dict[str, str] = {}

#: Top-level import -> why it is not declared in ``pyproject.toml``.
ALLOWED_UNDECLARED: dict[str, str] = {
    "arrayprobe_enhancements": (
        "Sibling distribution built from this repository's enhancements_uiops/ tree. It depends "
        "on this package, so declaring it here would make the dependency circular; the "
        "import is guarded and only reached when a run asks for an enhancement."
    ),
    "arrayprobe_soda2_enhancements": (
        "Sibling distribution built from this repository's enhancements_soda2/ tree. It "
        "depends on this package, so declaring it here would make the dependency "
        "circular; the import is guarded and only reached when a run asks for it."
    ),
}


def _local_packages() -> set[str]:
    return {p.name for p in _SRC.iterdir() if p.is_dir() and (p / "__init__.py").exists()} | {
        p.stem for p in _SRC.glob("*.py")
    }


def _third_party_imports() -> dict[str, set[str]]:
    """Top-level absolute imports outside the stdlib and this package, with their files."""
    local = _local_packages()
    found: dict[str, set[str]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top in sys.stdlib_module_names or top in local or top == "__future__":
                    continue
                found.setdefault(top, set()).add(path.relative_to(_ROOT).as_posix())
    return found


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared_distributions() -> set[str]:
    """Distribution names in ``dependencies`` and every optional-dependencies group."""
    text = _PYPROJECT.read_text(encoding="utf-8")
    declared: set[str] = set()
    block = re.search(r"^dependencies\s*=\s*\[(.*?)^\]", text, re.MULTILINE | re.DOTALL)
    if block:
        for line in block.group(1).splitlines():
            line = line.split("#", 1)[0]
            declared.update(re.findall(r'"([A-Za-z0-9_.\-]+)', line))
    section = re.search(r"^\[project\.optional-dependencies\]\s*$(.*?)(?=^\[)", text,
                        re.MULTILINE | re.DOTALL)
    if section:
        for line in section.group(1).splitlines():
            line = line.split("#", 1)[0]
            match = re.match(r"\s*[A-Za-z0-9_\-]+\s*=\s*\[(.*)\]", line)
            if match:
                declared.update(re.findall(r'"([A-Za-z0-9_.\-]+)', match.group(1)))
    return {_normalise(name) for name in declared}


@repo_only
class EveryThirdPartyImportIsDeclared(unittest.TestCase):

    def test_the_parsers_find_something_before_anything_is_concluded(self):
        declared = _declared_distributions()
        self.assertIn("numpy", declared, "core dependencies block not parsed")
        self.assertIn("scipy", declared, "optional-dependencies groups not parsed")
        imports = _third_party_imports()
        self.assertIn("numpy", imports, "the AST walk found no numpy import in src")

    def test_every_import_is_declared_or_allowlisted_with_a_reason(self):
        declared = _declared_distributions()
        missing = {
            top: sorted(files)
            for top, files in _third_party_imports().items()
            if _normalise(IMPORT_TO_DISTRIBUTION.get(top, top)) not in declared
            and top not in ALLOWED_UNDECLARED
        }
        self.assertEqual(missing, {}, "third-party imports in src not declared in "
                         "pyproject.toml (declare them, or allowlist with a reason)")

    def test_allowlist_entries_have_reasons_and_are_still_imported(self):
        imports = _third_party_imports()
        for name, reason in ALLOWED_UNDECLARED.items():
            with self.subTest(name=name):
                self.assertGreater(len(reason.split()), 10, "allowlist reason too thin")
                self.assertIn(name, imports, "allowlisted import no longer appears in src")


if __name__ == "__main__":
    unittest.main()

# A repository sweep: run before every full suite by the pre-suite check
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
