# SPDX-License-Identifier: BSD-3-Clause
"""A test that is skipped must still be counted.

**The defect this exists for, measured 2026-09-11.** the count script reported
**448** enhancement test methods and every public surface quoted it, while the suite's
own documented command printed `Ran 447 tests`. One test was discovered and never
executed, and nothing in the repository could see the difference.

The cause is a `unittest` detail with a sharp edge. A `SkipTest` raised inside
``setUpClass`` is recorded against an ``_ErrorHolder`` standing in for the whole class,
not against any test — so ``testsRun`` never increments and the skip never joins the
``skipped=N`` tally either. **The suite reports one FEWER test rather than one more
skip.** A method-level skip (``self.skipTest(...)``, a ``@skipUnless`` decorator on the
class or the method, or a raise from ``setUp``) is counted correctly, because
``startTest`` has already run by then.

So a class whose real-data coverage silently drops to zero looks identical, in the
summary line, to that class not existing. `enhancements_uiops/tests/test_wide_hollow_fix.py`
found this out the hard way and wrote the mechanism into a comment beside the raise —
which is the point. **The comment was right and the count still drifted**, because a
note at one site cannot stop the next site, and nothing reconciled the two numbers. The
rule was addressed to attention; this is the control (`/rule-failed-build-check`).

**What this sweeps, and what it deliberately allows.** It walks both test trees' source
with `ast` — no import, no execution, so a module whose dependencies are missing is
still checked — and fails on a `raise SkipTest`/`self.skipTest` reachable from a
``setUpClass`` body. A class-level ``@unittest.skipUnless`` decorator is **fine** and is
not swept: it sets ``__unittest_skip__`` on the class, which ``TestCase.run`` honours per
test method, so those skips are counted. The fix at a flagged site is always the same
shape — decide in ``setUpClass``, *raise* in ``setUp`` — and it costs nothing, because
the reason has already been computed by then.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from tests._repo import PKG_ROOT, repo_only  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

#: Both suites. A class-level skip is equally invisible in either, and the count that
#: went wrong was the enhancements one, so a sweep rooted only in this directory would
#: have missed the very defect that prompted it.
TEST_TREES = [PKG_ROOT / "tests", ROOT / "enhancements_uiops" / "tests"]

#: Classes allowed to skip from ``setUpClass``, each with the reason it cannot be moved
#: to ``setUp``. Empty, and meant to stay that way: the conversion is mechanical. A row
#: here is a claim that counting this test correctly is impossible, which is a strong
#: claim and should read like one.
#: **Empty since 2026-09-12, and the last row was paid off rather than
#: renewed.** ``LineNumbersLabelRealLines`` was allowed only because a
#: concurrent session owned `test_paper_line_numbers.py` when the other five
#: were converted on 2026-09-11; the allowance said so and called itself OWED.
#: It is converted now and the row is gone. Add one only for a class where
#: counting the test correctly is genuinely impossible -- and write the reason
#: so it reads like the strong claim it is.
ALLOWED: dict[str, str] = {}


def _skip_calls_in(node: ast.AST) -> bool:
    """Is a skip raised or called anywhere inside this node?"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Raise):
            exc = sub.exc
            if isinstance(exc, ast.Call):
                exc = exc.func
            name = getattr(exc, "attr", None) or getattr(exc, "id", None)
            if name == "SkipTest":
                return True
        if isinstance(sub, ast.Call):
            fn = sub.func
            if (getattr(fn, "attr", None) in {"skipTest", "skip"}
                    or getattr(fn, "id", None) == "skipTest"):
                return True
    return False


def _offenders() -> list[tuple[str, str, int]]:
    found = []
    for tree_dir in TEST_TREES:
        if not tree_dir.is_dir():
            continue
        for path in sorted(tree_dir.glob("test_*.py")):
            try:
                module = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:  # pragma: no cover - a broken test file fails elsewhere
                continue
            for cls in (n for n in ast.walk(module) if isinstance(n, ast.ClassDef)):
                for fn in cls.body:
                    if (isinstance(fn, ast.FunctionDef) and fn.name == "setUpClass"
                            and _skip_calls_in(fn)):
                        found.append((f"{path.name}::{cls.name}", str(path), fn.lineno))
    return found


@repo_only
class NoTestIsSkippedInvisibly(unittest.TestCase):
    def test_the_sweep_finds_some_test_files(self) -> None:
        """The empty-glob failure this project keeps finding, guarded here too."""
        counted = sum(len(list(d.glob("test_*.py"))) for d in TEST_TREES if d.is_dir())
        self.assertGreater(
            counted, 50,
            f"the sweep matched {counted} test files across {TEST_TREES}; it is looking "
            "in the wrong place and would pass having checked almost nothing")

    def test_no_setupclass_raises_skiptest(self) -> None:
        undeclared = [
            f"{name} ({path}:{line})"
            for name, path, line in _offenders()
            if name.split("::", 1)[1] not in ALLOWED
        ]
        self.assertEqual(
            [], undeclared,
            "these classes skip from setUpClass, so their tests are neither run nor "
            "counted as skipped -- the suite reports one fewer test instead of one more "
            "skip, and a coverage gap becomes indistinguishable from a class that does "
            "not exist. Decide in setUpClass and raise in setUp instead:\n  "
            + "\n  ".join(undeclared))

    def test_every_allowance_names_a_real_class_and_a_reason(self) -> None:
        """An exception list is a register and rots like one."""
        live = {name.split("::", 1)[1] for name, _, _ in _offenders()}
        for cls, reason in ALLOWED.items():
            with self.subTest(cls=cls):
                self.assertTrue(reason.strip(), f"{cls} is allowed with no reason")
                self.assertIn(
                    cls, live,
                    f"{cls} is in ALLOWED but no longer skips from setUpClass -- "
                    "remove the allowance")


if __name__ == "__main__":
    unittest.main()
