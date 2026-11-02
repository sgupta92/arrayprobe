# SPDX-License-Identifier: BSD-3-Clause
"""``docs/developer/CONSTANT_PROVENANCE.md`` names a ``file:line`` for every constant it claims
to trace, in the port and in the MATLAB. This test opens each named line and checks
that the quoted value token is on it, so a moved line or a changed value fails here
instead of leaving a stale citation.

It checks presence at the line only. The literature column is prose and is not, and
cannot be, verified by this test.
"""

from __future__ import annotations

import re
import unittest

from tests import _upstream  # noqa: E402
from tests._repo import PKG_ROOT, repo_only  # noqa: E402

DOC = PKG_ROOT / "docs" / "developer" / "CONSTANT_PROVENANCE.md"
# The port's lines ship with the package; the vendored MATLAB tree is repository-only,
# so the MATLAB half of each row is checked in a checkout and skipped in an sdist.
PREFIXES = {
    "M/": _upstream.source("uiops314"),
    "P/": PKG_ROOT / "src" / "arrayprobe",
    "V/": PKG_ROOT / "src" / "arrayprobe_uiops",
}
ROW = re.compile(r"^\| (C-\d+) \| (.*?) \| `([^`]+)` \| `([^`]+)` \| (.*?) \| .*\|$")
TOKEN = re.compile(r"`([^`]+)`")


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops314")


def _rows():
    for line in DOC.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if m:
            yield m.groups()


def _resolve(site: str):
    path, _, lineno = site.rpartition(":")
    for short, real in PREFIXES.items():
        if path.startswith(short):
            return real / path[len(short):], int(lineno)
    raise ValueError(f"{site}: no known prefix")


def _line(site: str) -> str:
    path, lineno = _resolve(site)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[lineno - 1]


class EveryRowNamesRealLines(unittest.TestCase):
    def test_the_table_is_non_empty(self):
        self.assertGreaterEqual(len(list(_rows())), 12)

    def _sites(self):
        for rid, _name, port_site, matlab_site, token_cell in _rows():
            tokens = TOKEN.findall(token_cell)
            self.assertIn(len(tokens), (1, 2), f"{rid}: value cell needs 1 or 2 tokens")
            port_tok, matlab_tok = (tokens * 2)[:2]
            yield rid, port_site, port_tok, matlab_site, matlab_tok

    @repo_only
    def test_each_cited_port_line_contains_its_value_token(self):
        for rid, port_site, port_tok, _msite, _mtok in self._sites():
            with self.subTest(row=rid, site=port_site):
                self.assertIn(port_tok, _line(port_site))

    @repo_only
    def test_each_cited_matlab_line_contains_its_value_token(self):
        for rid, _psite, _ptok, matlab_site, matlab_tok in self._sites():
            with self.subTest(row=rid, site=matlab_site):
                self.assertIn(matlab_tok, _line(matlab_site))


if __name__ == "__main__":
    unittest.main()
