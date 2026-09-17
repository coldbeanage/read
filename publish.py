#!/usr/bin/env python3
"""
read — publish a Markdown or HTML file to GitHub Pages as a beautiful page.

    ./publish.py FILE [--slug NAME] [--title T] [--desc D] [--raw] [--no-push]

Everything else is inferred. Prints the live URL.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
ASSETS = ROOT / "assets"
MANIFEST = DOCS / "manifest.json"

WPM = 225
RESERVED = {"assets", "manifest.json", "index.html", ".nojekyll", "404.html"}


# ----------------------------------------------------------------- helpers
def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, **kw)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[-\s_]+", "-", text).strip("-")
    return text or "document"


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Parse optional --- delimited frontmatter. Flat key: value only."""
    if not text.lstrip().startswith("---"):
        return {}, text
    body = text.lstrip()
    end = re.search(r"^---\s*$", body[3:], re.M)
    if not end:
        return {}, text
    raw, rest = body[3 : 3 + end.start()], body[3 + end.end() :]
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition(":")
            meta[k.strip().lower()] = v.strip().strip("\"'")
    return meta, rest.lstrip("\n")


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def first_sentences(text: str, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in (". ", "? ", "! "):
        i = cut.rfind(sep)
        if i > 60:
            return cut[: i + 1].strip()
    return cut.rsplit(" ", 1)[0].rstrip(",;:") + "\u2026"


# ----------------------------------------------------------------- render
class _InlineExtras:
    """~~del~~ and ==mark==, which python-markdown's `extra` does not provide."""

    @staticmethod
    def build():
        import xml.etree.ElementTree as ET

        from markdown.extensions import Extension
        from markdown.inlinepatterns import InlineProcessor

        class Simple(InlineProcessor):
            def __init__(self, pattern, tag):
                super().__init__(pattern)
                self.tag = tag

            def handleMatch(self, m, data):
                el = ET.Element(self.tag)
                el.text = m.group(1)
                return el, m.start(0), m.end(0)

        class Ext(Extension):
            def extendMarkdown(self, md):
                md.inlinePatterns.register(Simple(r"~~(.+?)~~", "del"), "del_ext", 175)
                md.inlinePatterns.register(Simple(r"==(.+?)==", "mark"), "mark_ext", 174)

        return Ext()


def render_markdown(src: str) -> tuple[str, list[dict]]:
    import markdown

    md = markdown.Markdown(
        extensions=[
            "extra", "codehilite", "toc", "admonition",
            "sane_lists", "smarty", "attr_list", "md_in_html",
            _InlineExtras.build(),
        ],
        extension_configs={
            "codehilite": {"guess_lang": False, "css_class": "codehilite"},
            "toc": {"permalink": True, "permalink_class": "headerlink", "permalink_title": "Link to this section"},
            "smarty": {"smart_dashes": True, "smart_quotes": True, "smart_ellipses": True},
        },
        output_format="html",
    )
    body = md.convert(src)
    return body, getattr(md, "toc_tokens", [])


def pygments_css() -> str:
    from pygments.formatters import HtmlFormatter

    light = HtmlFormatter(style="xcode").get_style_defs(".codehilite")
    dark = HtmlFormatter(style="github-dark").get_style_defs(".codehilite")
    dark_scoped = "\n".join(
        f'html[data-theme="dark"] {ln}' if ln.startswith(".codehilite") else ln
        for ln in dark.splitlines()
    )
    auto_scoped = "\n".join(
        f'html:not([data-theme="light"]) {ln}' if ln.startswith(".codehilite") else ln
        for ln in dark.splitlines()
    )
    return (
        f"{light}\n"
        f"{dark_scoped}\n"
        f"@media (prefers-color-scheme: dark) {{\n{auto_scoped}\n}}\n"
    )


def flatten_toc(tokens: list[dict], out: list[dict] | None = None) -> list[dict]:
    out = [] if out is None else out
    for t in tokens:
        if 2 <= t["level"] <= 4:
            out.append({"id": t["id"], "name": strip_tags(t["name"]), "level": t["level"]})
        flatten_toc(t.get("children", []), out)
    return out


def toc_html(items: list[dict], cls: str) -> str:
    if len(items) < 3:
        return ""
    lis = "".join(
        f'<li class="lvl-{i["level"]}"><a href="#{i["id"]}">{html.escape(i["name"])}</a></li>'
        for i in items
    )
    if cls == "side":
        return f'<nav class="toc" aria-label="Table of contents"><div class="toc-label">Contents</div><ul>{lis}</ul></nav>'
    return f'<details class="toc-inline"><summary>Contents</summary><ul>{lis}</ul></details>'


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title_esc}</title>
<meta name="description" content="{desc_esc}">
<meta name="color-scheme" content="light dark">
<meta property="og:type" content="article">
<meta property="og:title" content="{title_esc}">
<meta property="og:description" content="{desc_esc}">
<meta name="twitter:card" content="summary_large_image">
<link rel="preload" as="font" type="font/woff2" crossorigin href="{base}assets/fonts/literata-latin-400-normal.woff2">
<link rel="preload" as="font" type="font/woff2" crossorigin href="{base}assets/fonts/inter-latin-600-normal.woff2">
<link rel="stylesheet" href="{base}assets/fonts.css">
<link rel="stylesheet" href="{base}assets/theme.css">
<style>
{pyg}
</style>
<script>
  (function () {{
    try {{
      var t = localStorage.getItem("read-theme");
      if (t) document.documentElement.setAttribute("data-theme", t);
    }} catch (e) {{}}
  }})();
</script>
</head>
<body>
<div id="progress" role="presentation"></div>

<div class="topbar" id="topbar">
  <a class="home" href="{base}">read</a>
  <span class="crumb">{title_esc}</span>
  <button class="iconbtn" id="theme-toggle" type="button" aria-label="Toggle dark mode" title="Toggle dark mode">
    <svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
         stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
    <svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
         stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
  </button>
</div>

<div class="shell">
  <header class="doc-head">
    <!--SERIESKICKER--><!--/SERIESKICKER-->{kicker}
    <h1 class="title">{title_esc}</h1>
    {subtitle}
    <p class="meta"><span>{date_h}</span><span class="dot">&middot;</span><span>{minutes} min read</span><span class="dot">&middot;</span><span>{words:,} words</span></p>
  </header>
  {toc_inline}
  {toc_side}
  <main class="prose" id="prose">
{body}
  </main>
  <!--SERIESNAV--><!--/SERIESNAV-->
  <footer class="doc-foot">
    <span>{date_h}</span>
    <span><a href="{base}">&larr; all documents</a></span>
  </footer>
</div>

<script>
(function () {{
  var root = document.documentElement;
  var btn = document.getElementById("theme-toggle");
  btn.addEventListener("click", function () {{
    var cur = root.getAttribute("data-theme");
    if (!cur) cur = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    var next = cur === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try {{ localStorage.setItem("read-theme", next); }} catch (e) {{}}
  }});

  var bar = document.getElementById("progress");
  var topbar = document.getElementById("topbar");
  var ticking = false;
  function onScroll() {{
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () {{
      var h = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.width = (h > 0 ? Math.min(100, (window.scrollY / h) * 100) : 0) + "%";
      topbar.classList.toggle("scrolled", window.scrollY > 8);
      ticking = false;
    }});
  }}
  addEventListener("scroll", onScroll, {{ passive: true }});
  onScroll();

  document.querySelectorAll(".codehilite").forEach(function (block) {{
    var b = document.createElement("button");
    b.className = "copy-btn"; b.type = "button"; b.textContent = "Copy";
    b.addEventListener("click", function () {{
      var code = block.querySelector("code");
      navigator.clipboard.writeText(code ? code.innerText : "").then(function () {{
        b.textContent = "Copied"; b.classList.add("done");
        setTimeout(function () {{ b.textContent = "Copy"; b.classList.remove("done"); }}, 1600);
      }});
    }});
    block.appendChild(b);
  }});

  var links = [].slice.call(document.querySelectorAll("nav.toc a"));
  if (links.length) {{
    var map = {{}};
    var targets = links.map(function (a) {{
      var el = document.getElementById(decodeURIComponent(a.hash.slice(1)));
      if (el) map[el.id] = a;
      return el;
    }}).filter(Boolean);
    var seen = new Set();
    var obs = new IntersectionObserver(function (entries) {{
      entries.forEach(function (e) {{
        if (e.isIntersecting) seen.add(e.target.id); else seen.delete(e.target.id);
      }});
      var active = targets.filter(function (t) {{ return seen.has(t.id); }})[0];
      if (!active) {{
        for (var i = targets.length - 1; i >= 0; i--) {{
          if (targets[i].getBoundingClientRect().top < 120) {{ active = targets[i]; break; }}
        }}
      }}
      links.forEach(function (a) {{ a.classList.remove("active"); }});
      if (active && map[active.id]) map[active.id].classList.add("active");
    }}, {{ rootMargin: "-80px 0px -70% 0px", threshold: 0 }});
    targets.forEach(function (t) {{ obs.observe(t); }});
  }}
}})();
</script>
</body>
</html>
"""


INDEX = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>read</title>
<meta name="description" content="Published documents.">
<meta name="color-scheme" content="light dark">
<link rel="preload" as="font" type="font/woff2" crossorigin href="assets/fonts/literata-latin-400-normal.woff2">
<link rel="preload" as="font" type="font/woff2" crossorigin href="assets/fonts/inter-latin-600-normal.woff2">
<link rel="stylesheet" href="assets/fonts.css">
<link rel="stylesheet" href="assets/theme.css">
<script>
  (function () {{
    try {{
      var t = localStorage.getItem("read-theme");
      if (t) document.documentElement.setAttribute("data-theme", t);
    }} catch (e) {{}}
  }})();
</script>
</head>
<body>
<div class="topbar" id="topbar">
  <a class="home" href="./">read</a>
  <span class="crumb"></span>
  <button class="iconbtn" id="theme-toggle" type="button" aria-label="Toggle dark mode" title="Toggle dark mode">
    <svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
         stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
    <svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
         stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
  </button>
</div>
<div class="shell">
  <header class="index-head">
    <h1>read</h1>
    <p>{count} document{plural}.</p>
  </header>
  {list_html}
</div>
<script>
(function () {{
  var root = document.documentElement;
  document.getElementById("theme-toggle").addEventListener("click", function () {{
    var cur = root.getAttribute("data-theme");
    if (!cur) cur = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    var next = cur === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try {{ localStorage.setItem("read-theme", next); }} catch (e) {{}}
  }});
  var topbar = document.getElementById("topbar");
  addEventListener("scroll", function () {{
    topbar.classList.toggle("scrolled", window.scrollY > 8);
  }}, {{ passive: true }});
}})();
</script>
</body>
</html>
"""


def refresh_series(entries: list[dict]) -> int:
    """Rewrite the series kicker + prev/next block in every page of every series."""
    groups: dict[str, list[dict]] = {}
    for e in entries:
        if e.get("series"):
            groups.setdefault(e["series"], []).append(e)

    touched = 0
    for name, members in groups.items():
        members.sort(key=lambda e: (e.get("part") is None, e.get("part") or 0, e.get("published", "")))
        total = len(members)
        for i, e in enumerate(members):
            page = DOCS / e["slug"] / "index.html"
            if not page.exists():
                continue
            n = e.get("part") or (i + 1)
            kicker = (
                f'<p class="kicker">{html.escape(name)}'
                f'<span class="part"> \u00b7 Part {n} of {total}</span></p>'
            )

            prev_e = members[i - 1] if i > 0 else None
            next_e = members[i + 1] if i < total - 1 else None
            cards = []
            if prev_e:
                cards.append(
                    f'<a class="sn prev" href="../{prev_e["slug"]}/">'
                    f'<span class="dir">Previous</span>'
                    f'<span class="t">{html.escape(prev_e["title"])}</span></a>'
                )
            if next_e:
                cards.append(
                    f'<a class="sn next" href="../{next_e["slug"]}/">'
                    f'<span class="dir">Next</span>'
                    f'<span class="t">{html.escape(next_e["title"])}</span></a>'
                )
            others = "".join(
                f'<li{" class=\"here\"" if m["slug"] == e["slug"] else ""}>'
                f'<a href="../{m["slug"]}/"><span class="n">{m.get("part") or j + 1}</span>'
                f'{html.escape(m["title"])}</a></li>'
                for j, m in enumerate(members)
            )
            nav = (
                '<nav class="series-nav" aria-label="Series navigation">'
                f'<div class="sn-row">{"".join(cards)}</div>'
                f'<div class="sn-all"><div class="sn-label">{html.escape(name)}</div>'
                f'<ol>{others}</ol></div></nav>'
            )

            txt = page.read_text(encoding="utf-8")
            txt = re.sub(r"<!--SERIESKICKER-->.*?<!--/SERIESKICKER-->",
                         f"<!--SERIESKICKER-->{kicker}<!--/SERIESKICKER-->", txt, flags=re.S)
            txt = re.sub(r"<!--SERIESNAV-->.*?<!--/SERIESNAV-->",
                         f"<!--SERIESNAV-->{nav}<!--/SERIESNAV-->", txt, flags=re.S)
            page.write_text(txt, encoding="utf-8")
            touched += 1
    return touched


def _index_item(e: dict) -> str:
    desc = f'<span class="d">{html.escape(e["description"])}</span>' if e.get("description") else ""
    return (
        f'<li><a href="{e["slug"]}/">'
        f'<span class="t">{html.escape(e["title"])}</span>{desc}'
        f'<span class="m"><span>{e["date_h"]}</span><span>&middot;</span>'
        f'<span>{e["minutes"]} min</span></span></a></li>'
    )


def build_index(entries: list[dict]) -> str:
    if not entries:
        return INDEX.format(count=0, plural="s", list_html='<p class="empty">Nothing published yet.</p>')

    # group series into one block, ordered by the newest member
    series: dict[str, list[dict]] = {}
    singles: list[dict] = []
    for e in entries:
        (series.setdefault(e["series"], []) if e.get("series") else singles).append(e)

    blocks: list[tuple[str, str]] = []
    for name, members in series.items():
        members.sort(key=lambda m: (m.get("part") is None, m.get("part") or 0, m.get("published", "")))
        newest = max(m.get("published", "") for m in members)
        mins = sum(m.get("minutes", 0) for m in members)
        inner = "".join(
            f'<li><a href="{m["slug"]}/">'
            f'<span class="n">{m.get("part") if m.get("part") is not None else i + 1}</span>'
            f'<span class="body"><span class="t">{html.escape(m["title"])}</span>'
            + (f'<span class="d">{html.escape(m["description"])}</span>' if m.get("description") else "")
            + f'<span class="m">{m["minutes"]} min</span></span></a></li>'
            for i, m in enumerate(members)
        )
        blocks.append((newest,
            f'<section class="series-block"><h2 class="series-title">{html.escape(name)}'
            f'<span class="series-meta">{len(members)} parts &middot; {mins} min</span></h2>'
            f'<ol class="series-list">{inner}</ol></section>'))

    for e in singles:
        blocks.append((e.get("published", ""), f'<ul class="doclist">{_index_item(e)}</ul>'))

    blocks.sort(key=lambda b: b[0], reverse=True)
    n = len(entries)
    return INDEX.format(count=n, plural="" if n == 1 else "s",
                        list_html="".join(b[1] for b in blocks))


# ----------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description="Publish a document to GitHub Pages.")
    ap.add_argument("file", help="path to .md or .html")
    ap.add_argument("--slug", help="URL path segment (default: from filename)")
    ap.add_argument("--title", help="override the title")
    ap.add_argument("--desc", help="override the description")
    ap.add_argument("--raw", action="store_true", help="force: publish HTML untouched")
    ap.add_argument("--theme", action="store_true", help="force: re-wrap HTML in the read theme")
    ap.add_argument("--no-push", action="store_true", help="build locally, skip git")
    ap.add_argument("--series", help="group with other docs under this series name")
    ap.add_argument("--part", type=int, help="position within the series")
    args = ap.parse_args()

    src_path = Path(args.file).expanduser().resolve()
    if not src_path.is_file():
        die(f"no such file: {src_path}")

    text = src_path.read_text(encoding="utf-8", errors="replace")
    meta, text = split_frontmatter(text)
    ext = src_path.suffix.lower()
    is_html = ext in (".html", ".htm")
    standalone = is_html and re.search(r"<html[\s>]", text, re.I) is not None
    # A standalone HTML file that brings its own styling was designed by someone;
    # pass it through. A bare one gets the read theme so it is still pleasant.
    self_styled = standalone and bool(
        re.search(r"<style[\s>]", text, re.I)
        or re.search(r'<link[^>]+stylesheet', text, re.I)
        or re.search(r'\bstyle\s*=\s*"', text)
    )
    passthrough = args.raw or (self_styled and not args.theme)

    slug = slugify(args.slug or meta.get("slug") or src_path.stem)
    if slug in RESERVED:
        die(f"slug '{slug}' is reserved; pass --slug")

    # ---- title / description
    title = args.title or meta.get("title")
    body_html, toc_items = "", []

    if is_html:
        if not passthrough:
            if standalone:
                m = re.search(r"<body[^>]*>(.*)</body>", text, re.S | re.I)
                body_html = m.group(1) if m else text
            else:
                body_html = text
            # a lone <h1> at the top is promoted into the title block
            if not title:
                m = re.match(r"\s*<h1[^>]*>(.*?)</h1>", body_html, re.S | re.I)
                if m:
                    title = strip_tags(m.group(1))
                    body_html = body_html[m.end():]
        if not title:
            m = (re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
                 or re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S | re.I))
            title = strip_tags(m.group(1)) if m is not None else src_path.stem.replace("-", " ").title()
        if passthrough:
            plain_for_stats = strip_tags(re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I))
        else:
            plain_for_stats = None
    else:
        # pull a leading H1 out of the body so it isn't duplicated under the title block
        if not title:
            m = re.match(r"\s*#\s+(.+?)\s*$", text, re.M)
            if m and text[: m.start()].strip() == "":
                title = m.group(1).strip()
                text = text[m.end():].lstrip("\n")
        if not title:
            title = src_path.stem.replace("-", " ").replace("_", " ").strip().capitalize()
        body_html, toc_tokens = render_markdown(text)
        toc_items = flatten_toc(toc_tokens)

    if not passthrough:
        body_html = re.sub(r"<table>", '<div class="table-wrap"><table>', body_html)
        body_html = re.sub(r"</table>", "</table></div>", body_html)

    plain = strip_tags(body_html)
    if is_html and passthrough:
        plain = plain_for_stats or plain
    words = len(plain.split())
    minutes = max(1, round(words / WPM))
    desc = args.desc or meta.get("description") or meta.get("desc") or ""
    if not desc:
        desc = first_sentences(plain)
    subtitle_src = meta.get("subtitle") or ""

    now = dt.datetime.now().astimezone()
    date_iso = meta.get("date") or now.strftime("%Y-%m-%d")
    try:
        date_h = dt.datetime.strptime(date_iso[:10], "%Y-%m-%d").strftime("%d %B %Y")
    except ValueError:
        date_iso, date_h = now.strftime("%Y-%m-%d"), now.strftime("%d %B %Y")

    # ---- write
    out_dir = DOCS / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    if passthrough:
        page = text
    else:
        page = PAGE.format(
            title_esc=html.escape(title),
            desc_esc=html.escape(desc, quote=True),
            base="../",
            pyg=pygments_css(),
            kicker=f'<p class="kicker">{html.escape(meta["kicker"])}</p>' if meta.get("kicker") else "",
            subtitle=f'<p class="subtitle">{html.escape(subtitle_src)}</p>' if subtitle_src else "",
            date_h=date_h,
            minutes=minutes,
            words=words,
            toc_side=toc_html(toc_items, "side"),
            toc_inline=toc_html(toc_items, "inline"),
            body=body_html,
        )
    (out_dir / "index.html").write_text(page, encoding="utf-8")

    # copy sibling assets referenced relatively (images next to the source)
    copied = 0
    for ref in set(re.findall(r'(?:src|href)="(?!https?:|//|#|/|data:|mailto:)([^"]+)"', page)):
        cand = (src_path.parent / ref).resolve()
        if cand.is_file() and src_path.parent.resolve() in cand.parents:
            dest = out_dir / ref
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cand, dest)
            copied += 1

    # ---- manifest + index
    entries = []
    if MANIFEST.exists():
        try:
            entries = json.loads(MANIFEST.read_text())
        except json.JSONDecodeError:
            entries = []
    entries = [e for e in entries if e.get("slug") != slug]
    series = args.series or meta.get("series") or ""
    part = args.part if args.part is not None else (
        int(meta["part"]) if str(meta.get("part", "")).isdigit() else None
    )
    entries.append({
        "slug": slug, "title": title, "description": desc,
        "published": date_iso, "date_h": date_h,
        "words": words, "minutes": minutes,
        "series": series, "part": part,
        "updated": now.strftime("%Y-%m-%dT%H:%M:%S%z"),
    })
    entries = [e for e in entries if (DOCS / e["slug"] / "index.html").exists()]
    MANIFEST.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    series_touched = refresh_series(entries)
    (DOCS / "index.html").write_text(build_index(entries), encoding="utf-8")
    (DOCS / ".nojekyll").touch()

    shutil.copytree(ASSETS, DOCS / "assets", dirs_exist_ok=True)

    # ---- publish
    repo = os.environ.get("READ_REPO", "")
    url = ""
    if not args.no_push:
        r = run(["git", "remote", "get-url", "origin"])
        origin = r.stdout.strip()
        if not origin:
            die("no git remote 'origin'. Run setup first.")
        m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", origin)
        if not m:
            die(f"cannot parse origin: {origin}")
        owner, name = m.group(1), m.group(2)
        url = f"https://{owner.lower()}.github.io/{name}/{slug}/"

        run(["git", "add", "-A"])
        st = run(["git", "status", "--porcelain"]).stdout.strip()
        if st:
            c = run(["git", "commit", "-m", f"publish: {title} ({slug})"])
            if c.returncode != 0:
                die(f"commit failed:\n{c.stdout}\n{c.stderr}")
        branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip() or "main"
        p = run(["git", "push", "origin", branch])
        if p.returncode != 0:
            die(f"push failed:\n{p.stdout}\n{p.stderr}")

    print(json.dumps({
        "slug": slug, "title": title, "words": words, "minutes": minutes,
        "headings": len(toc_items), "assets_copied": copied,
        "series": series or None, "series_pages_updated": series_touched,
        "local": str(out_dir / "index.html"),
        "url": url, "index_url": url.rsplit(slug + "/", 1)[0] if url else "",
        "pushed": not args.no_push,
    }, indent=2))


if __name__ == "__main__":
    main()
