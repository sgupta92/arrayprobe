# SPDX-License-Identifier: BSD-3-Clause
"""Every variable ``imgProc_sm.m`` defines is one the port knows how to write.

WHY THIS EXISTS. ``imgProc_sm.m:443`` defines ``image_bin_stats`` and ``:929``
writes it, under the optional ``iCalcAllDiodeStats`` flag. The port accepts that
flag (``imgproc.py:400,466-471``), validates it, and stamps the global attribute
``'Optional parameters active' = 'Per-particle diode statistics'`` — and then
never writes the variable. It appears **zero** times in ``src/``.

So a file produced with that flag announces per-particle diode statistics and
does not contain them. That is worse than not supporting the flag: the honest
refusal already exists elsewhere in the same module for
``save_workspace_mat``, which raises rather than pretending.

Nothing caught it. The fidelity tests compare *values* of variables both sides
write; a variable one side never writes at all is invisible to them, because
there is nothing to compare. This check works the other way round — it starts
from the original's own ``netcdf.defVar`` calls and asks whether the port has
heard of each name.

WHY ONLY ``imgProc_sm``. Its variable names are string literals on both sides,
so the comparison is exact. ``sizeDist.m``'s nineteen ``REJ_`` twins are built
in the port by prefixing (``sizedist.py:1397``), so a literal search reports
false positives for every one of them. A weaker check that cried wolf on
nineteen names would be turned off, and an ignored check is worse than none.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests import _upstream  # noqa: E402
from tests._repo import PKG_ROOT, repo_only  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MATLAB = (_upstream.source("uiops314") / "imgProc_sm.m")
SRC = PKG_ROOT / "src" / "arrayprobe"

_DEFVAR = re.compile(r"defVar\(\s*f\s*,\s*'([A-Za-z0-9_]+)'")

#: Variables the original defines that the port does NOT write, each with the
#: reason. This is a RATCHET: it may shrink freely, and growing it requires
#: editing this file, which is the point. An entry here is a recorded defect or
#: a recorded decision — never a way to make the check quiet.
KNOWN_MISSING: dict[str, str] = {
    # Empty, and that is the ratchet's whole point: `image_bin_stats` sat here
    # from 2026-09-06 with a defect note, and was removed in the same edit that
    # transcribed imgProc_sm.m:801-803 and :928-930 into imgproc.py. All 49
    # variables the original defines are now written by the port.
}


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops314")


def matlab_variables() -> set[str]:
    return set(_DEFVAR.findall(MATLAB.read_text(encoding="utf-8", errors="replace")))


def port_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in sorted(SRC.rglob("*.py")))


@unittest.skipUnless(MATLAB.is_file(), f"MATLAB source not present at {MATLAB}")
class ThePortKnowsEveryVariableTheOriginalDefines(unittest.TestCase):
    @repo_only
    def test_the_matlab_source_parses(self):
        """A regex that matches nothing would make every other test vacuous."""
        found = matlab_variables()
        self.assertGreater(
            len(found), 40,
            f"only {len(found)} defVar names parsed out of imgProc_sm.m; the "
            "pattern has probably stopped matching")

    @repo_only
    def test_every_defined_variable_appears_in_the_port(self):
        text = port_text()
        missing = sorted(
            v for v in matlab_variables()
            if v not in KNOWN_MISSING and f"'{v}'" not in text and f'"{v}"' not in text)
        self.assertEqual(
            missing, [],
            "imgProc_sm.m defines these variables and the port never names "
            f"them, so a file it writes is missing them silently: {missing}. "
            "Either write them, refuse the option that produces them, or add "
            "them to KNOWN_MISSING with a reason.")

    def test_the_known_missing_list_only_shrinks(self):
        """The ratchet. If a name here is now written, remove it in the same
        edit — an exemption outliving its defect silently waives a future one."""
        text = port_text()
        fixed = sorted(v for v in KNOWN_MISSING
                       if f"'{v}'" in text or f'"{v}"' in text)
        self.assertEqual(
            fixed, [],
            f"these are written by the port now and must be removed from "
            f"KNOWN_MISSING: {fixed}")

    def test_every_exemption_states_a_reason(self):
        vague = sorted(k for k, why in KNOWN_MISSING.items() if len(why) < 80)
        self.assertEqual(vague, [], f"exemptions with no real reason: {vague}")

    @repo_only
    def test_exemptions_name_variables_the_original_actually_defines(self):
        """An exemption for a name the original does not define is dead text
        that will one day be read as evidence about the original."""
        stale = sorted(set(KNOWN_MISSING) - matlab_variables())
        self.assertEqual(stale, [], f"exemptions for undefined variables: {stale}")


if __name__ == "__main__":
    unittest.main()
