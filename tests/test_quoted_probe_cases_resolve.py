# SPDX-License-Identifier: BSD-3-Clause
"""Every probe case a shipped surface quotes as available resolves from shipped modules alone.

Found 2026-10-18 by running the docs in a fresh install: ``tune settings --probe-case
arm-ena-2ds`` exited 2 because the module that registers that case does not ship. This test
collects every name quoted as ``--probe-case NAME`` in ``docs/*.md``, as ``NAME is always
available`` in the CLI's help text, and as ``probe_case = "NAME"`` in shipped examples, then
resolves each in a fresh interpreter in which every ``arrayprobe_uiops.register_*`` module the
release does not ship is made unimportable. In the checkout the shipped set comes from the
release builder (``allowed`` and not ``never_ship``); in a built tree every file present ships.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._repo import REPO_ROOT

_CASE = r"([a-z0-9][a-z0-9.\-]*[a-z0-9])"
_PATTERNS = (re.compile(r"--probe-case[ =]+" + _CASE + r"(?![\w<>])"),
             re.compile(_CASE + r" is\s+always\s+available"),
             re.compile(r"probe_case\s*=\s*\"" + _CASE + "\""))
_SURFACES = ("docs/*.md", "examples/**/*.md", "examples/**/*.toml", "examples/**/*.ipynb",
             "src/arrayprobe/cli.py")


def _builder(root: Path):
    path = root / "scripts" / "build_release_tree.py"
    if not path.is_file():
        return None, None
    spec = importlib.util.spec_from_file_location("_probe_case_builder", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod      # before exec: the builder defines dataclasses
    spec.loader.exec_module(mod)
    rules = mod.parse_allowlist(
        (root / "scripts" / "release_allowlist.txt").read_text(encoding="utf-8"))
    return mod, rules


def _ships(root: Path, rel: str, mod, rules) -> bool:
    return mod is None or (mod.allowed(rel, rules) is not None and mod.never_ship(rel) is None)


def quoted_cases(root: Path) -> dict[str, list[str]]:
    """``{case name: [shipped files quoting it]}``."""
    mod, rules = _builder(root)
    found: dict[str, list[str]] = {}
    for pattern in _SURFACES:
        for p in sorted(root.glob(pattern)):
            rel = p.relative_to(root).as_posix()
            if not p.is_file() or not _ships(root, rel, mod, rules):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            for rx in _PATTERNS:
                for m in rx.finditer(text):
                    found.setdefault(m.group(1), []).append(rel)
    return found


def blocked_modules(root: Path) -> list[str]:
    """``arrayprobe_uiops.register_*`` modules present here that the release does not ship."""
    mod, rules = _builder(root)
    out = []
    for p in sorted((root / "src" / "arrayprobe_uiops").glob("register_*.py")):
        rel = p.relative_to(root).as_posix()
        if not _ships(root, rel, mod, rules):
            out.append("arrayprobe_uiops." + p.stem)
    return out


_CHILD = r"""
import importlib.abc, json, sys
blocked, names = set(json.loads(sys.argv[1])), json.loads(sys.argv[2])
class _Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name in blocked:
            raise ModuleNotFoundError(f"No module named {name!r} (not shipped)", name=name)
        return None
sys.meta_path.insert(0, _Block())
from arrayprobe.tune.settings import resolve_probe_defaults
from arrayprobe.driver import run_flight
# The batch driver's preflight resolver (run_flight.main, the --probe-case refusal), reached
# the way main() reaches it, so a name a run would refuse fails here too.
driver_resolve = run_flight.resolve_run_probe_case
bad = {}
for n in names:
    for who, resolve in (("tune", resolve_probe_defaults), ("driver", driver_resolve)):
        try:
            resolve(n)
        except Exception as exc:
            bad[n] = f"{who}: {type(exc).__name__}: {exc}"[:200]
            break
print(json.dumps(bad))
"""


def unresolved(names: list[str], blocked: list[str]) -> dict[str, str]:
    r = subprocess.run([sys.executable, "-c", _CHILD, json.dumps(blocked), json.dumps(names)],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise AssertionError(f"resolver subprocess failed:\n{r.stderr[-2000:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


class QuotedProbeCasesResolve(unittest.TestCase):

    def test_every_quoted_case_resolves_from_shipped_modules(self):
        found = quoted_cases(REPO_ROOT)
        self.assertIn("v35-2ds-ladder-fix", found, "the scan found nothing it should")
        bad = unresolved(sorted(found), blocked_modules(REPO_ROOT))
        self.assertEqual(
            bad, {}, "shipped surfaces quote probe cases a fresh install cannot resolve: "
            + "; ".join(f"{n} in {sorted(set(found[n]))}: {e}" for n, e in bad.items()))

    def test_the_guard_fires_on_a_bogus_case(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "docs").mkdir()
            (root / "docs" / "99-bogus.md").write_text(
                "```bash\narrayprobe tune settings --probe-case no-such-case-zz\n```\n",
                encoding="utf-8")
            found = quoted_cases(root)      # no builder here: every file present ships
            self.assertEqual(found, {"no-such-case-zz": ["docs/99-bogus.md"]})
            self.assertIn("no-such-case-zz", unresolved(sorted(found), []))

    def test_an_unshipped_registration_module_is_blocked(self):
        if not (REPO_ROOT / "src" / "arrayprobe_uiops" / "register_arm_ena_2ds.py").is_file():
            self.skipTest("the ARM ENA registration module is absent (a built release tree)")
        if not (REPO_ROOT / "scripts" / "build_release_tree.py").is_file():
            self.skipTest("The release builder is not distributed with the package")
        blocked = blocked_modules(REPO_ROOT)
        self.assertIn("arrayprobe_uiops.register_arm_ena_2ds", blocked)
        self.assertIn("arm-ena-2ds", unresolved(["arm-ena-2ds"], blocked))


if __name__ == "__main__":
    unittest.main()
