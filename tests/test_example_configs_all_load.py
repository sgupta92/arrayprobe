# SPDX-License-Identifier: BSD-3-Clause
"""Every shipped example config must load, and the one kind of file that cannot is pinned.

``examples/configs/`` holds run configurations that a stranger copies and edits. A config
that stopped loading (a renamed key, a removed section) would be documentation of a thing
that used to work, and the per-example tests only load the files they name. This module
globs the whole tree:

* every ``*.toml`` except ``*.presets.toml`` loads through ``arrayprobe.config.load_config``,
  one ``subTest`` per file;
* a ``*.presets.toml`` is a campaign-presets template (``[[campaign]]`` tables, read by the
  ``presets =`` key / ``run_flight --presets``), which ``load_config`` rejects by design as an
  unknown section; each one is instead checked to parse as TOML, to hold a non-empty
  ``campaign`` list, and to be named by some config's ``presets =`` line (a commented-out
  line counts: the example documents the key without enabling a template that holds
  replace-me values);
* a must-fire self-test shows the loader does raise on a bad config, so the load check
  can fail, and that a presets file is refused by the run-config loader.
"""

from __future__ import annotations

import re
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from tests._profile_registry_guard import module_hooks
from tests._repo import REPO_ROOT, repo_only

# Loading a config can import its profile module, which registers a profile; restore the
# registry (and drop the cached modules) so nothing leaks into later modules.
setUpModule, _restore_registry = module_hooks()

CONFIGS = REPO_ROOT / "examples" / "configs"
_PRESETS_KEY = re.compile(r"""^\s*#?\s*presets\s*=\s*["']([^"']+)["']""", re.MULTILINE)


def _tomls() -> list[Path]:
    return sorted(CONFIGS.rglob("*.toml"))


def _is_presets(path: Path) -> bool:
    return path.name.endswith(".presets.toml")


def tearDownModule():  # noqa: N802 -- unittest's name
    _restore_registry()


def _load(path: Path):
    """``load_config(path)`` with the file's own directory reachable for ``profile_module``."""
    from arrayprobe.config import load_config
    here = str(path.parent)
    sys.path.insert(0, here)
    try:
        return load_config(path)
    finally:
        sys.path.remove(here)


# Reads examples/configs/, which the sdist does not ship.
@repo_only
class EveryExampleRunConfigLoads(unittest.TestCase):
    def test_the_glob_finds_the_examples(self):
        run_configs = [p for p in _tomls() if not _is_presets(p)]
        self.assertGreaterEqual(len(run_configs), 1, f"no run config under {CONFIGS}")

    def test_every_run_config_loads(self):
        for path in (p for p in _tomls() if not _is_presets(p)):
            with self.subTest(config=str(path.relative_to(CONFIGS))):
                cfg = _load(path)
                self.assertIsNotNone(cfg)


# Reads examples/configs/, which the sdist does not ship.
@repo_only
class EveryPresetsTemplateIsWellFormed(unittest.TestCase):
    def test_each_presets_file_parses_and_holds_campaigns(self):
        for path in (p for p in _tomls() if _is_presets(p)):
            with self.subTest(presets=str(path.relative_to(CONFIGS))):
                doc = tomllib.loads(path.read_text(encoding="utf-8"))
                campaigns = doc.get("campaign")
                self.assertIsInstance(campaigns, list)
                self.assertTrue(campaigns, f"{path.name} declares no [[campaign]] table")

    def test_each_presets_file_is_named_by_a_config(self):
        referenced: set[tuple[Path, str]] = set()
        for cfg in (p for p in _tomls() if not _is_presets(p)):
            for name in _PRESETS_KEY.findall(cfg.read_text(encoding="utf-8")):
                referenced.add((cfg.parent, name))
        for path in (p for p in _tomls() if _is_presets(p)):
            with self.subTest(presets=str(path.relative_to(CONFIGS))):
                self.assertIn(
                    (path.parent, path.name), referenced,
                    f"no config's `presets =` line names {path.name}")


class TheCheckCanFail(unittest.TestCase):
    """The load check is only worth having if a bad file makes it raise."""

    def test_a_config_with_an_unknown_section_is_refused(self):
        from arrayprobe.config import ConfigError, load_config
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.toml"
            bad.write_text('[definitely_not_a_section]\nkey = "value"\n', encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                load_config(bad)
            self.assertIn("unknown section", str(ctx.exception))

    def test_a_presets_file_is_refused_by_the_run_config_loader(self):
        from arrayprobe.config import ConfigError, load_config
        with tempfile.TemporaryDirectory() as tmp:
            presets = Path(tmp) / "x.presets.toml"
            presets.write_text('[[campaign]]\nname = "X"\n', encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(presets)

    def test_the_presets_filter_matches_only_the_suffix(self):
        self.assertTrue(_is_presets(Path("b.presets.toml")))
        self.assertFalse(_is_presets(Path("presets.toml")))
        self.assertFalse(_is_presets(Path("b.toml")))


if __name__ == "__main__":
    unittest.main()


# A repository sweep: run before every full suite by the pre-suite check
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True
