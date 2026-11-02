# SPDX-License-Identifier: BSD-3-Clause
"""Build the documentation site in ``docs/`` from the pages in ``docs/``.

GitHub Pages serves ``docs/`` on the ``master`` branch directly (Settings → Pages → "Deploy
from a branch", folder ``/docs``).  ``.nojekyll`` keeps Jekyll out of it, so what is committed
is exactly what is served -- no build step on GitHub's side, no theme gem, and the same output
can be opened locally with ``file://``.

Nothing here is a dependency of the port: this script uses the standard library only, and the
markdown subset it understands is the one the pages actually use (see
``tests/test_docs_site.py`` for the pinned behaviour).

Usage, from the repository root::

    .venv/Scripts/python.exe docs/_build/build.py [--out DIR] [--check]
    .venv/Scripts/python.exe docs/_build/build.py --refresh-docs

``--check`` builds into a temporary directory and fails if the result differs from ``--out``,
so a stale site is a test failure rather than a surprise. ``--out`` never accepts ``docs/``
itself, which holds the page sources; ``--refresh-docs`` is the one way to update the built
pages committed there (``*.html``, ``search-index.js``), copying only those from a fresh build.
"""

from __future__ import annotations

import argparse
import filecmp
import html
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGES = ROOT.parent

# --------------------------------------------------------------------------
# A small markdown subset: headings, paragraphs, fenced code, lists, tables,
# blockquotes, rules, and the inline set (code, bold, italic, links).
# --------------------------------------------------------------------------

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
# An image: `![alt](path)`. Applied before _LINK, which would otherwise take the
# bracket and leave a stray "!".
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_AUTOLINK = re.compile(r"(?<![\"'=(])\bhttps://[^\s<>()\[\]]+")


# A line that is nothing but one HTML comment. Generators (profiledoc.py and its
# kin) bracket the regions they own with such lines in the .md; they are for the
# generators' --check, never for readers, so render() drops them.
_COMMENT_ONLY = re.compile(r"^\s*<!--(?:(?!-->).)*-->\s*$")


# GitHub renders these pages too and slugs headings its own way (underscores and the text
# around apostrophes kept), so a heading whose GitHub anchor differs from the site's also
# carries the GitHub one: a link written for GitHub then resolves on the site as well.
# tests/test_docs_site.py asserts this equals the release-tree builder's github_slug.
def github_slug(heading: str) -> str:
    """GitHub's heading anchor, computed from the rendered text: images dropped, a link's text
    kept, code and emphasis markers dropped, lower-case, punctuation other than ``-`` and ``_``
    dropped, each space to a hyphen."""
    h = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", heading)
    h = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", h)
    h = re.sub(r"[`*~]", "", h).strip().lower()
    return re.sub(r"[^\w\- ]", "", h).replace(" ", "-")


def _slug(text: str) -> str:
    """The site's earlier heading anchor, still emitted so a link a reader holds keeps working."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# A page links another page by its source file, ``04-validation.md#anchor``, so the link
# also resolves where the sources are read directly (GitHub renders ``docs/``);
# the build rewrites it to the built name, ``validation.html#anchor``. Any other relative
# target is written as GitHub resolves it from ``pages/`` and re-based onto ``docs/``:
# ``../figures/x.svg`` becomes ``figures/x.svg`` (the build copies ``figures/`` in), and a
# link up to the repository's examples folder loses one level the same way. Absolute URLs
# and bare ``#anchor`` links pass through unchanged. ``tests/test_markdown_links.py``
# resolves every link both ways.
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
SITE = ROOT.parents[1] / "_site"


def _page_href(stem: str) -> str:
    slug = stem.split("-", 1)[1]
    return "index.html" if slug == "index" else f"{slug}.html"


def site_href(target: str) -> str:
    """A link target as written in ``pages/*.md`` -> the same target in the built site."""
    if not target or target.startswith(("#", "/")) or _SCHEME.match(target):
        return target
    path, sep, frag = target.partition("#")
    if not path:
        return target
    resolved = Path(os.path.normpath(PAGES / path))
    if resolved.parent == PAGES and resolved.suffix == ".md":
        if not resolved.is_file():
            raise ValueError(f"link to a page that does not exist: {target}")
        return _page_href(resolved.stem) + sep + frag
    # Anything under docs/ (figures/, developer/) is copied into the site at the same
    # relative path, so it is linked from the site root; the rest from the repository.
    if PAGES in resolved.parents:
        rebased = os.path.relpath(resolved, PAGES).replace(os.sep, "/")
    else:
        rebased = os.path.relpath(resolved, SITE).replace(os.sep, "/")
    if path.endswith("/") and not rebased.endswith("/"):
        rebased += "/"
    return rebased + sep + frag


def inline(text: str) -> str:
    """Inline markdown to HTML.  Code spans are protected from every other rule."""
    spans: list[str] = []

    def stash(m):
        spans.append(html.escape(m.group(1)))
        return f"\x00{len(spans) - 1}\x00"

    text = _INLINE_CODE.sub(stash, text)
    text = html.escape(text)
    text = _IMAGE.sub(lambda m: f'<img src="{site_href(m.group(2))}" alt="{m.group(1)}">',
                      text)
    text = _LINK.sub(lambda m: f'<a href="{site_href(m.group(2))}">{m.group(1)}</a>', text)
    text = _AUTOLINK.sub(lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    text = text.replace("&amp;mdash;", "&mdash;").replace("--", "&ndash;")
    return re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{spans[int(m.group(1))]}</code>", text)


def _table(rows: list[str]) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], cells[2:]
    out = ['<div class="tablewrap"><table><thead><tr>']
    out += [f"<th>{inline(c)}</th>" for c in head]
    out.append("</tr></thead><tbody>")
    for row in body:
        out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


_ITEM = re.compile(r"^\s*([-*]|\d+\.) ")


def _fence(lang: str, body: list[str]) -> str:
    """A fenced code block, escaped verbatim; the copy-button script finds every ``<pre>``."""
    cls = f' class="lang-{html.escape(lang)}"' if lang else ""
    return f"<pre><code{cls}>{html.escape(chr(10).join(body))}</code></pre>"


def _item_html(segments: list[tuple[str, object]]) -> str:
    """One list item: its first prose run inline, later runs as paragraphs, fences as-is."""
    parts: list[str] = []
    for n, (kind, val) in enumerate(segments):
        if kind == "h":
            parts.append(str(val))
        elif val:
            text = inline(" ".join(val))  # type: ignore[arg-type]
            parts.append(text if n == 0 else f"<p>{text}</p>")
    return "".join(parts)


def render(md: str) -> tuple[str, list[tuple[int, str, str]]]:
    """Markdown to (html, table-of-contents) where the ToC is (level, text, anchor)."""
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    toc: list[tuple[int, str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            lang = line[3:].strip()
            body: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1
            out.append(_fence(lang, body))
            continue
        if _COMMENT_ONLY.match(line):
            # A line that is wholly an HTML comment is a generator marker
            # (``<!-- PROFILEDOC:START -->`` and its kin) and is dropped from the
            # rendered output. Only whole lines qualify: a ``<!--`` inside prose
            # or a fenced block is content and stays escaped and visible.
            i += 1
            continue
        if re.match(r"^#{1,4} ", line):
            level = len(line) - len(line.lstrip("#"))
            text = line[level:].strip()
            # The id is GitHub's slug, so a link written for GitHub resolves on the site
            # as-is; the earlier site slug stays as an inner anchor where the two differ,
            # so a link a reader already holds keeps working.
            anchor = github_slug(text)
            legacy = _slug(text)
            if level <= 3:
                toc.append((level, re.sub(r"[`*]", "", text), anchor))
            keep = f'<a id="{legacy}"></a>' if legacy != anchor else ""
            out.append(f'<h{level} id="{anchor}">{keep}{inline(text)}</h{level}>')
            i += 1
            continue
        if re.match(r"^\s*\|.*\|\s*$", line) and i + 1 < len(lines) \
                and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            rows = []
            while i < len(lines) and re.match(r"^\s*\|.*\|\s*$", lines[i]):
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue
        if _ITEM.match(line):
            first = re.match(r"^\s*(\d+)\. ", line)
            ordered = first is not None
            # Each item is a list of segments: ("t", prose lines) or ("h", rendered html).
            items: list[list[tuple[str, object]]] = []
            while i < len(lines):
                cur = lines[i]
                if _ITEM.match(cur):
                    items.append([("t", [_ITEM.sub("", cur, count=1)])])
                    i += 1
                elif cur.startswith("  ") and cur.lstrip().startswith("```") and items:
                    # A fenced block indented under an item belongs to that item:
                    # dedent it by the fence's own indent and render it as a top-level
                    # fence is rendered.
                    indent = len(cur) - len(cur.lstrip(" "))
                    lang = cur.lstrip()[3:].strip()
                    body = []
                    i += 1
                    while i < len(lines) and not lines[i].lstrip().startswith("```"):
                        b = lines[i]
                        body.append(b[min(indent, len(b) - len(b.lstrip(" "))):])
                        i += 1
                    i += 1
                    items[-1].append(("h", _fence(lang, body)))
                elif cur.startswith("  ") and cur.strip() and items:
                    last = items[-1][-1]
                    if last[0] == "t":
                        last[1].append(cur.strip())  # type: ignore[union-attr]
                    else:
                        items[-1].append(("t", [cur.strip()]))
                    i += 1
                elif not cur.strip() and items:
                    # A blank line ends the list unless what follows is indented under
                    # the item, or is another item of the same kind.
                    j = i
                    while j < len(lines) and not lines[j].strip():
                        j += 1
                    nxt = lines[j] if j < len(lines) else ""
                    same = (bool(re.match(r"^\s*\d+\. ", nxt)) if ordered
                            else bool(re.match(r"^\s*[-*] ", nxt)))
                    if nxt.startswith("  ") or same:
                        if nxt.startswith("  ") and not _ITEM.match(nxt) \
                                and not nxt.lstrip().startswith("```"):
                            items[-1].append(("t", []))  # a new paragraph in the item
                        i = j
                    else:
                        break
                else:
                    break
            tag = "ol" if ordered else "ul"
            start = int(first.group(1)) if first else 1
            attr = f' start="{start}"' if ordered and start != 1 else ""
            out.append(f"<{tag}{attr}>" + "".join(f"<li>{_item_html(x)}</li>" for x in items)
                       + f"</{tag}>")
            continue
        if line.startswith("> "):
            quote: list[str] = []
            while i < len(lines) and lines[i].startswith("> "):
                quote.append(lines[i][2:])
                i += 1
            out.append(f"<blockquote>{inline(' '.join(quote))}</blockquote>")
            continue
        if re.match(r"^-{3,}$", line.strip()):
            out.append("<hr>")
            i += 1
            continue
        if not line.strip():
            i += 1
            continue
        para = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
                r"^(#{1,4} |```|> |\s*[-*] |\s*\d+\. |\s*\|)", lines[i]) \
                and not re.match(r"^-{3,}$", lines[i].strip()) \
                and not _COMMENT_ONLY.match(lines[i]):
            para.append(lines[i])
            i += 1
        out.append(f"<p>{inline(' '.join(para))}</p>")
    return "\n".join(out), toc


# --------------------------------------------------------------------------
# Site assembly
# --------------------------------------------------------------------------

def read_pages() -> list[dict]:
    """Each page is ``pages/NN-slug.md`` whose first line is ``# Title``.

    An optional second line ``> one-line description`` becomes the page's subtitle and its
    search-index summary.
    """
    pages = []
    for path in sorted(PAGES.glob("*.md")):
        if path.name.endswith(".public.md"):
            continue  # a release-only twin (clidoc.py --public); the release tree renames it
        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        title = lines[0].lstrip("# ").strip()
        subtitle = ""
        body_start = 1
        if len(lines) > 1 and lines[1].startswith("> "):
            subtitle = lines[1][2:].strip()
            body_start = 2
        slug = path.stem.split("-", 1)[1]
        pages.append({"slug": slug, "title": title, "subtitle": subtitle,
                      "md": "\n".join(lines[body_start:]).strip(),
                      "href": "index.html" if slug == "index" else f"{slug}.html"})
    pages.sort(key=lambda p: 0 if p["slug"] == "index" else 1)
    return pages


CSS = """
:root{--bg:#fbfbfc;--surface:#fff;--sidebar:#f4f5f7;--ink:#1c2126;--muted:#5b646d;
--line:#dde1e6;--accent:#1e6f68;--accent-soft:#e6f1f0;--code-bg:#eef1f3;--code-ink:#28303a;
--warn:#8a6d1f;--warn-bg:#fbf4e0;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#14181b;--surface:#1a1f23;
--sidebar:#171c1f;--ink:#e6eaed;--muted:#98a2ab;--line:#2f383e;--accent:#48b2a5;
--accent-soft:#1b2c2a;--code-bg:#212930;--code-ink:#d6dce1;--warn:#d8b866;--warn-bg:#2b2617;}}
:root[data-theme="dark"]{--bg:#14181b;--surface:#1a1f23;--sidebar:#171c1f;--ink:#e6eaed;
--muted:#98a2ab;--line:#2f383e;--accent:#48b2a5;--accent-soft:#1b2c2a;--code-bg:#212930;
--code-ink:#d6dce1;--warn:#d8b866;--warn-bg:#2b2617;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 -apple-system,"Segoe UI",
system-ui,Roboto,sans-serif;}
a{color:var(--accent)}
.layout{display:grid;grid-template-columns:270px minmax(0,1fr);min-height:100vh}
nav.side{background:var(--sidebar);border-right:1px solid var(--line);padding:1.4rem 1rem 3rem;
position:sticky;top:0;height:100vh;overflow-y:auto}
nav.side .brand{font-weight:700;font-size:1.05rem;letter-spacing:-.01em;display:block;
text-decoration:none;color:var(--ink)}
nav.side .brand small{display:block;font-weight:400;font-size:.75rem;color:var(--muted);
margin-top:.2rem;letter-spacing:.02em}
nav.side input{width:100%;margin:1rem 0 .6rem;padding:.45rem .6rem;border:1px solid var(--line);
border-radius:6px;background:var(--surface);color:var(--ink);font:inherit;font-size:.85rem}
nav.side ul{list-style:none;margin:0;padding:0}
nav.side li a{display:block;padding:.34rem .55rem;border-radius:6px;text-decoration:none;
color:var(--ink);font-size:.9rem}
nav.side li a:hover{background:var(--accent-soft)}
nav.side li a.active{background:var(--accent-soft);color:var(--accent);font-weight:600}
nav.side .sub{margin-left:.6rem;border-left:1px solid var(--line);padding-left:.4rem}
nav.side .sub a{font-size:.82rem;color:var(--muted);padding:.2rem .5rem}
main{padding:2.4rem 2.4rem 6rem;max-width:900px}
main h1{font-size:2rem;letter-spacing:-.02em;margin:0 0 .3rem;text-wrap:balance}
main .standfirst{color:var(--muted);font-size:1.05rem;margin:0 0 2rem}
main h2{font-size:1.35rem;margin:2.6rem 0 .7rem;padding-bottom:.35rem;
border-bottom:1px solid var(--line);text-wrap:balance}
main h3{font-size:1.05rem;margin:1.8rem 0 .5rem}
main h4{font-size:.95rem;margin:1.4rem 0 .4rem;color:var(--muted);text-transform:uppercase;
letter-spacing:.06em}
p,li{max-width:72ch}
code{background:var(--code-bg);color:var(--code-ink);padding:.1em .35em;border-radius:4px;
font:.87em/1.5 "Cascadia Code",Consolas,monospace}
pre{background:var(--code-bg);color:var(--code-ink);border:1px solid var(--line);
border-radius:8px;padding:.9rem 1.1rem;overflow-x:auto}
pre code{background:none;padding:0;font-size:.83rem}
blockquote{margin:1.2rem 0;padding:.7rem 1rem;background:var(--warn-bg);color:var(--ink);
border-left:3px solid var(--warn);border-radius:0 6px 6px 0}
blockquote p{margin:0}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;margin:1.1rem 0;
background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:.87rem}
th,td{text-align:left;padding:.5rem .75rem;border-bottom:1px solid var(--line);
vertical-align:top}
th{background:var(--bg);font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;
color:var(--muted)}
tr:last-child td{border-bottom:none}
hr{border:none;border-top:1px solid var(--line);margin:2.4rem 0}
footer{margin-top:4rem;padding-top:1.2rem;border-top:1px solid var(--line);color:var(--muted);
font-size:.83rem}
#results{margin:.2rem 0 .8rem;font-size:.83rem}
#results a{display:block;padding:.25rem .5rem;border-radius:6px;text-decoration:none}
#results a:hover{background:var(--accent-soft)}
#results .ctx{color:var(--muted);font-size:.75rem;display:block}
.codewrap{position:relative}
.codewrap pre{padding-right:4.6rem}
.copybtn{position:absolute;top:.45rem;right:.45rem;padding:.15rem .55rem;font:inherit;
font-size:.75rem;color:var(--muted);background:var(--surface);border:1px solid var(--line);
border-radius:5px;cursor:pointer;opacity:.85}
.copybtn:hover,.copybtn:focus-visible{color:var(--accent);border-color:var(--accent);opacity:1}
.copybtn:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
@media(max-width:860px){.layout{grid-template-columns:1fr}
nav.side{position:static;height:auto;border-right:none;border-bottom:1px solid var(--line)}
main{padding:1.6rem 1.1rem 4rem}}
"""

JS = """
const idx = window.__SEARCH__ || [];
const box = document.getElementById('q'), res = document.getElementById('results');
if (box) box.addEventListener('input', () => {
  const q = box.value.trim().toLowerCase();
  res.innerHTML = '';
  if (q.length < 2) return;
  const hits = [];
  for (const p of idx) {
    const i = p.text.toLowerCase().indexOf(q);
    if (p.title.toLowerCase().includes(q) || i >= 0)
      hits.push([p, i < 0 ? '' : p.text.slice(Math.max(0, i - 40), i + 60)]);
    if (hits.length >= 8) break;
  }
  for (const [p, ctx] of hits) {
    const a = document.createElement('a');
    a.href = p.href; a.textContent = p.title;
    if (ctx) { const s = document.createElement('span'); s.className = 'ctx';
               s.textContent = '…' + ctx + '…'; a.appendChild(s); }
    res.appendChild(a);
  }
});
"""

# A "Copy" button on every code block. Inline on each page that has a <pre>, so it needs
# no extra request; without JavaScript no button is made and the block reads as before.
# Prompts ("$ ", ">>> ", "... ") are stripped only when every non-empty line carries one,
# so a block that merely contains a "$" is copied verbatim.
COPY_MARKER = '<script id="copy-button">'
COPY_JS = r"""
(function () {
  function clean(t) {
    var lines = t.replace(/\n$/, '').split('\n');
    var full = lines.filter(function (l) { return l.trim() !== ''; });
    if (!full.length) return t;
    if (full.every(function (l) { return /^\$ /.test(l); }))
      return lines.map(function (l) { return l.replace(/^\$ /, ''); }).join('\n');
    if (full.every(function (l) { return /^(>>>|\.\.\.)( |$)/.test(l); }))
      return lines.map(function (l) { return l.replace(/^(>>>|\.\.\.) ?/, ''); }).join('\n');
    return lines.join('\n');
  }
  function fallback(text) {
    var ta = document.createElement('textarea');
    ta.value = text; ta.setAttribute('readonly', '');
    ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    return ok ? Promise.resolve() : Promise.reject();
  }
  function copy(text) {
    if (navigator.clipboard && window.isSecureContext)
      return navigator.clipboard.writeText(text).catch(function () { return fallback(text); });
    return fallback(text);
  }
  document.querySelectorAll('main pre').forEach(function (pre) {
    var wrap = document.createElement('div');
    wrap.className = 'codewrap';
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'copybtn'; b.textContent = 'Copy';
    b.setAttribute('aria-label', 'Copy code to clipboard');
    b.addEventListener('click', function () {
      copy(clean(pre.innerText)).then(function () {
        b.textContent = 'Copied';
      }, function () {
        b.textContent = 'Press Ctrl+C';
      });
      clearTimeout(b._t);
      b._t = setTimeout(function () { b.textContent = 'Copy'; }, 1500);
    });
    wrap.appendChild(b);
  });
})();
"""
COPY_SCRIPT = COPY_MARKER + COPY_JS.rstrip() + "\n</script>\n"


#: A path to material not part of this package, kept out of the shipped search index.
DEV_PATH = re.compile(r"\b(?:archive|project)/[\w./#-]+")


#: Subdirectories of the output that the build does not own and never clears.
KEEP = frozenset({"developer"})


def build(out: Path) -> None:
    if out.resolve() == PAGES.resolve() or PAGES.resolve() in out.resolve().parents:
        raise SystemExit(f"refusing to build into {out}: it holds the page sources "
                         "(to refresh the built pages committed there, run "
                         "docs/_build/build.py --refresh-docs)")
    pages = read_pages()
    # `docs/developer/` holds the hand-written developer notes since the 2026-10-08
    # move to the repository root; the site is generated around it, never over it.
    if out.exists():
        for child in out.iterdir():
            if child.name in KEEP:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    out.mkdir(parents=True, exist_ok=True)
    (out / ".nojekyll").write_text("", encoding="utf-8", newline="\n")
    (out / "style.css").write_text(CSS.strip() + "\n", encoding="utf-8", newline="\n")
    (out / "search.js").write_text(JS.strip() + "\n", encoding="utf-8", newline="\n")
    for sub in ("figures", "developer"):
        if (PAGES / sub).is_dir():
            shutil.copytree(PAGES / sub, out / sub, dirs_exist_ok=True)

    # The index is shipped data, so it carries no path to material not part of this package
    # (`archive/...`, `project/...`): the release builder refuses those (R12).
    index = [{"title": p["title"], "href": p["href"],
              "text": re.sub(r"\s+", " ", re.sub(r"[#`*|>-]", " ",
                                                 DEV_PATH.sub(" ", p["md"])))[:4000]}
             for p in pages]
    (out / "search-index.js").write_text(
        "window.__SEARCH__ = " + json.dumps(index) + ";\n", encoding="utf-8", newline="\n")

    for page in pages:
        body, toc = render(page["md"])
        nav = []
        for other in pages:
            active = ' class="active"' if other is page else ""
            nav.append(f'<li><a href="{other["href"]}"{active}>{html.escape(other["title"])}</a>')
            if other is page and toc:
                nav.append('<ul class="sub">')
                nav += [f'<li><a href="#{a}">{html.escape(t)}</a></li>'
                        for lvl, t, a in toc if lvl == 2]
                nav.append("</ul>")
            nav.append("</li>")
        doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(page["title"])} · arrayprobe</title>
<meta name="description" content="{html.escape(page["subtitle"])}">
<link rel="stylesheet" href="style.css">
</head>
<body>
<div class="layout">
<nav class="side">
<a class="brand" href="index.html">arrayprobe<small>UIOOPS and SODA-2, ported to Python</small></a>
<input id="q" type="search" placeholder="Search the docs…" autocomplete="off">
<div id="results"></div>
<ul>{"".join(nav)}</ul>
</nav>
<main>
<h1>{html.escape(page["title"])}</h1>
{f'<p class="standfirst">{inline(page["subtitle"])}</p>' if page["subtitle"] else ""}
{body}
<footer>
BSD-3-Clause · derived from UIOOPS v3.1.4 (McFarquhar group) ·
an independent port; it is not a UIOOPS or SODA-2 release. ·
<a href="https://github.com/sgupta92/arrayprobe">source</a>
</footer>
</main>
</div>
<script src="search-index.js"></script>
<script src="search.js"></script>
{COPY_SCRIPT if "<pre>" in body else ""}</body>
</html>
"""
        (out / page["href"]).write_text(doc, encoding="utf-8", newline="\n")


def _differs(a: Path, b: Path) -> list[str]:
    # Honour KEEP exactly as build() does: a top-level entry it never
    # clears (docs/developer/) is not the generator's output, so it is
    # never reported stale.
    def _ours(root: Path) -> set[str]:
        return {p.relative_to(root).as_posix() for p in root.rglob("*")
                if p.is_file() and p.relative_to(root).parts[0] not in KEEP}
    names = _ours(a) | _ours(b)
    bad = []
    for n in sorted(names):
        pa, pb = a / n, b / n
        if not pa.is_file() or not pb.is_file() or not filecmp.cmp(pa, pb, shallow=False):
            bad.append(n)
    return bad


def _built_outputs(root: Path) -> set[str]:
    """The built pages committed beside the sources: top-level ``*.html`` and the index.

    The same set ``tests/test_docs_site.py``'s ``SiteIsCurrent`` compares."""
    names = {p.name for p in root.glob("*.html") if p.is_file()}
    if (root / "search-index.js").is_file():
        names.add("search-index.js")
    return names


def refresh_docs(target: Path = PAGES) -> list[str]:
    """Refresh the built pages committed in ``docs/`` without touching the sources.

    ``build()`` refuses to write into the sources directory, because it clears what it does
    not own; this builds into a temporary directory instead and copies across only the built
    outputs (top-level ``*.html`` and ``search-index.js``) that differ. A committed ``*.html``
    the build no longer produces is removed, since the comparison reports it stale. The
    ``*.md`` sources, every subdirectory (``_build``, ``figures``, ``developer``) and every
    other file are never written. Returns the changed names, each prefixed ``updated``,
    ``added`` or ``removed``."""
    changed: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp) / "site"
        build(site)
        fresh = _built_outputs(site)
        for name in sorted(fresh | _built_outputs(target)):
            src, dst = site / name, target / name
            if name not in fresh:
                dst.unlink()
                changed.append(f"removed {name}")
            elif not dst.is_file():
                shutil.copyfile(src, dst)
                changed.append(f"added {name}")
            elif src.read_bytes() != dst.read_bytes():
                shutil.copyfile(src, dst)
                changed.append(f"updated {name}")
    return changed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None, help=f"default: {SITE}")
    ap.add_argument("--refresh-docs", action="store_true",
                    help="refresh the built pages committed in docs/ (*.html, search-index.js) "
                         "from a fresh build, leaving the *.md sources and subdirectories alone")
    ap.add_argument("--check", action="store_true",
                    help="build into a temp dir and fail on any error; with an existing "
                         "--out given explicitly, also report where it differs")
    args = ap.parse_args(argv)
    if args.refresh_docs:
        if args.out or args.check:
            ap.error("--refresh-docs takes neither --out nor --check")
        changed = refresh_docs()
        for line in changed:
            print(line)
        print(f"docs/ built pages: {len(changed)} changed" if changed
              else "docs/ built pages already current")
        return 0
    out = Path(args.out) if args.out else SITE
    if args.check:
        # Nothing built is committed (the site is built by CI), so the check is that a fresh
        # build succeeds: a link to a missing page raises in site_href.
        with tempfile.TemporaryDirectory() as tmp:
            build(Path(tmp) / "site")
            n = len(list((Path(tmp) / "site").glob("*.html")))
            bad = _differs(Path(tmp) / "site", out) if args.out and out.exists() else []
        if bad:
            print(f"{out} is stale: " + ", ".join(bad), file=sys.stderr)
            return 1
        print(f"site builds: {n} pages")
        return 0
    build(out)
    print(f"wrote {len(list(out.glob('*.html')))} pages to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
