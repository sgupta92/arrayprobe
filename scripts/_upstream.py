# SPDX-License-Identifier: BSD-3-Clause
"""Re-export of ``tests/_upstream.py`` for developer tools: one resolver."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "tests" / "_upstream.py"
_NAME = "_arrayprobe_tests_upstream"
if _NAME in sys.modules:
    _mod = sys.modules[_NAME]
else:
    _spec = importlib.util.spec_from_file_location(_NAME, _SRC)
    assert _spec is not None and _spec.loader is not None
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_NAME] = _mod
    _spec.loader.exec_module(_mod)

ROOT = _mod.ROOT
TREES = _mod.TREES
REQUIRE_ENV = _mod.REQUIRE_ENV
tree = _mod.tree
source = _mod.source
SOURCES = _mod.SOURCES
manifest_path = _mod.manifest_path
require = _mod.require
verify = _mod.verify

__all__ = ["REQUIRE_ENV", "ROOT", "SOURCES", "TREES", "manifest_path", "require", "source",
           "tree", "verify"]
