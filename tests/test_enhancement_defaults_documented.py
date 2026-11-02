# SPDX-License-Identifier: BSD-3-Clause
"""Every page that states an enhancement's default agrees with the registry.

The registry (``arrayprobe_enhancements.registry``, ``arrayprobe_soda2_enhancements.registry``)
is the code of record: ``default_on`` is False for every module, and the only default-on path is
each registry's ``PROTECTIVE`` set, applied by the driver. A documentation table row whose first
cell names a module and that claims "ON by default" (or "default ON") for a module the registry
leaves off is a mismatch. Historical clauses ("briefly ON by default before then", "(ON by
default before then)") are not current claims and are ignored.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = [
    "enhancements_uiops/docs/applicability_matrix.md",
    "enhancements_uiops/docs/CORRECTIONS.md",
    "enhancements_soda2/docs/CORRECTIONS.md",
    "docs/05-enhancements.md",
    "docs/23-enhancements-by-engine.md",
    "docs/25-enhancements-by-stage.md",
]
_ROW = re.compile(r"^\|\s*`([a-z0-9_]+?)(?:\.py)?`\s*\|")
_HISTORICAL = re.compile(
    r"briefly\s+ON\s+by\s+default[^|;)]*|\(ON by default before then\)|"
    r"ON by default before then|it had been default ON|was (?:default )?ON by default",
    re.IGNORECASE)
_ON_CLAIM = re.compile(r"\bON by default\b|\bdefault[- ]ON\b", re.IGNORECASE)


def registry_defaults():
    """Module name -> True where the package or its driver turns it on by default."""
    out = {}
    try:
        from arrayprobe_enhancements import registry as ru
        for name, spec in ru.REGISTRY.items():
            out[name] = bool(spec.default_on) or name in ru.PROTECTIVE
    except ImportError:
        pass
    try:
        from arrayprobe_soda2_enhancements import registry as rs
        for name, spec in rs.load_all().items():
            out[name] = bool(getattr(spec, "default_on", False)) or name in rs.PROTECTIVE
    except ImportError:
        pass
    return out


def mismatches(text, defaults):
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        m = _ROW.match(line)
        if not m or m.group(1) not in defaults:
            continue
        current = _HISTORICAL.sub("", line)
        if _ON_CLAIM.search(current) and not defaults[m.group(1)]:
            found.append((n, m.group(1)))
    return found


class TestDefaultsDocumented(unittest.TestCase):
    def setUp(self):
        self.defaults = registry_defaults()
        if not self.defaults:
            self.skipTest("neither enhancement registry is importable")

    def test_pages_agree_with_registry(self):
        bad = []
        for rel in PAGES:
            p = ROOT / rel
            if p.exists():
                bad += [(rel, n, name) for n, name in
                        mismatches(p.read_text(encoding="utf-8"), self.defaults)]
        self.assertEqual(bad, [], "pages claim ON by default for modules the registry has off")

    def test_guard_fires_on_a_synthetic_mismatch(self):
        name = next(k for k, v in self.defaults.items() if not v)
        self.assertEqual(mismatches(f"| `{name}` | x | **ON by default** |", self.defaults),
                         [(1, name)])
        self.assertEqual(mismatches(f"| `{name}.py` | x | default ON |", self.defaults),
                         [(1, name)])

    def test_historical_clause_is_not_a_claim(self):
        name = next(k for k, v in self.defaults.items() if not v)
        line = f"| `{name}` | OFF by default since 2026-09-16 (briefly ON by default before then) |"
        self.assertEqual(mismatches(line, self.defaults), [])


if __name__ == "__main__":
    unittest.main()
