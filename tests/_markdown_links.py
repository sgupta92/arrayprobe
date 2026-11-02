# SPDX-License-Identifier: BSD-3-Clause
"""Link-resolution helpers shared by the markdown and notebook link tests.

Moved out of ``test_markdown_links.py`` (2026-10-16): that file checks the development
repository's own layout and does not ship, while ``test_notebook_links.py`` and
``test_notebook_names_are_current.py`` ship and import these helpers, so the release
builder refused to write the tree (rule R13: a shipped test may not import an unshipped one).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


#: ``[text](target)`` and ``![alt](target)``; the target stops at whitespace or ``)``.
MD_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
#: ``href="..."`` / ``src="..."`` in built HTML.
HTML_LINK = re.compile(r"""\b(?:href|src)\s*=\s*["']([^"']+)["']""")
_FENCE = re.compile(r"^[ \t]*(```+|~~~+)[^\n]*\n.*?^[ \t]*\1[ \t]*$", re.M | re.S)
_CODE_SPAN = re.compile(r"(`+)(?:(?!\1)[^\n])+?\1")
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
#: A reference-style definition, ``[name]: target``, which ``MD_LINK`` does not see.
MD_REF_DEF = re.compile(r"^[ \t]{0,3}\[[^\]]+\]:\s*<?([^\s>]+)>?", re.M)
#: Raw ``<a href>`` / ``<img src>`` written inside markdown; GitHub resolves them the same way.
MD_RAW_HTML = re.compile(r"""<(?:a|img)\b[^>]*?\b(?:href|src)\s*=\s*["']([^"']+)["']""", re.I)

#: Markdown read on GitHub whose relative links must resolve there. Generated
#: and hand-written alike; ``archive/`` is excluded by design (kept unchanged).
GITHUB_MARKDOWN_GLOBS = (
    "*.md",
    "enhancements_uiops/*.md",
    "docs/*.md",
    "docs/developer/**/*.md",
    "enhancements_uiops/docs/**/*.md",
)


def _strip_code(text: str) -> str:
    """Remove fenced blocks and code spans: a link written inside code is an example."""
    return _CODE_SPAN.sub("", _FENCE.sub("", text))


def _is_relative(target: str) -> bool:
    return bool(target) and not target.startswith(("#", "/")) and not _SCHEME.match(target)


def _git_tree(root: Path) -> frozenset[str] | None:
    """Every tracked file and every directory holding one, as GitHub serves them.

    GitHub resolves a link against the committed tree, case-sensitively. The disk of a
    Windows clone is case-insensitive and also holds gitignored and untracked files, so
    a disk check passes links that 404 on GitHub. ``None`` when git is unavailable (an
    unpacked sdist), and the callers then fall back to the disk.
    """
    import subprocess
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True,
                             check=True, timeout=120).stdout.decode("utf-8")
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return None
    tree: set[str] = set()
    for f in filter(None, out.split("\0")):
        tree.add(f)
        while "/" in f:
            f = f.rsplit("/", 1)[0]
            tree.add(f)
    return frozenset(tree) or None


_TREE: list[frozenset[str] | None] = []


def _tracked() -> frozenset[str] | None:
    if not _TREE:
        _TREE.append(_git_tree(ROOT))
    return _TREE[0]
