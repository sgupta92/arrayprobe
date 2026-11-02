# SPDX-License-Identifier: BSD-3-Clause
"""The generic SODA-2 example config resolves to the same run as the one it was copied from.

``examples/configs/soda2/2ds_spec.toml`` is the configuration the getting-started notebooks run.
It was copied from ``examples/configs/2ds_soda2/und_2ds_spec.toml`` with only the names, paths and
labels changed. A config file selects and never describes a threshold, so the proof that nothing
else changed is the loader's own output: both files are read through
:func:`arrayprobe.config.load_config` and every resolved field is compared, the two paths
(``fn``, ``pth``) and the ``source`` the object records being the only exclusions.
"""

import dataclasses
import re
import unittest
from pathlib import Path

from tests._repo import repo_only

from arrayprobe.config import load_config

ROOT = Path(__file__).resolve().parents[1]
GENERIC = ROOT / "examples" / "configs" / "soda2" / "2ds_spec.toml"
ORIGINAL = ROOT / "examples" / "configs" / "2ds_soda2" / "und_2ds_spec.toml"
PATH_KEYS = ("fn", "pth")

# Campaign and institution names (and the local data folder) the generic copy must not carry.
NAMES = re.compile(r"\b(UND|ORACLES|ARM|ENA|NASA|NCAR|P-3)\b|local-data")


def _resolved(path):
    cfg = load_config(path)
    out = dataclasses.asdict(cfg)
    out.pop("source")
    out["soda2"] = {k: v for k, v in out["soda2"].items() if k not in PATH_KEYS}
    return cfg, out


@repo_only
class TestGenericSoda2Config(unittest.TestCase):

    def test_generic_config_loads_as_a_soda2_run(self):
        cfg, _ = _resolved(GENERIC)
        self.assertEqual(cfg.run, {"engine": "soda2"})
        self.assertIsNone(cfg.profile)

    @unittest.skipUnless(ORIGINAL.is_file(), "the campaign-named config is not in this tree")
    def test_resolves_to_the_same_run_configuration_as_its_source(self):
        _, generic = _resolved(GENERIC)
        _, original = _resolved(ORIGINAL)
        self.assertEqual(generic, original)

    @unittest.skipUnless(ORIGINAL.is_file(), "the campaign-named config is not in this tree")
    def test_only_the_paths_differ(self):
        generic, original = load_config(GENERIC).soda2, load_config(ORIGINAL).soda2
        self.assertEqual(set(generic), set(original))
        differing = sorted(k for k in generic if generic[k] != original[k])
        self.assertEqual(differing, sorted(PATH_KEYS))

    def test_names_no_campaign_or_institution(self):
        for path in (GENERIC, GENERIC.with_name("README.md")):
            hits = [m.group(0) for m in NAMES.finditer(path.read_text(encoding="utf-8"))]
            self.assertEqual(hits, [], f"{path.name} names {sorted(set(hits))}")


if __name__ == "__main__":
    unittest.main()
