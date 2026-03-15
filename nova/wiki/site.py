from __future__ import annotations

import contextlib
import html
import http.server
import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


_INLINE_PATTERN = re.compile(r"`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)")


@dataclass
class WikiHeading:
    level: int
    text: str
    anchor: str


@dataclass
class WikiPage:
    title: str
    source_path: Path
    href: str
    excerpt: str
    headings: list[WikiHeading]
    content_html: str
    search_text: str


@dataclass
class WikiBuildResult:
    source_dir: str
    output_dir: str
    page_count: int
    home_page: str
    generated_files: list[str] = field(default_factory=list)
    pages: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_dir": self.source_dir,
            "output_dir": self.output_dir,
            "page_count": self.page_count,
            "home_page": self.home_page,
            "generated_files": self.generated_files,
            "pages": self.pages,
        }


def _slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "section"


def _convert_href(raw_href: str) -> str:
    href = raw_href.strip()
    if not href or href.startswith("#"):
        return href
    parsed = urlparse(href)
    if parsed.scheme or href.startswith("//"):
        return href

    anchor = ""
    if "#" in href:
        href, anchor = href.split("#", 1)
        anchor = f"#{anchor}"

    cleaned = href.replace("\\", "/")
    if cleaned in {".", "./", ""}:
        return f"Home.html{anchor}"
    if cleaned.endswith(".md"):
        cleaned = f"{cleaned[:-3]}.html"
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return f"{cleaned}{anchor}"


def _render_plain_fragment(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    return escaped


def _render_inline(text: str) -> str:
    parts: list[str] = []
    last_index = 0
    for match in _INLINE_PATTERN.finditer(text):
        parts.append(_render_plain_fragment(text[last_index:match.start()]))
        code_value, label, href = match.groups()
        if code_value is not None:
            parts.append(f"<code>{html.escape(code_value)}</code>")
        else:
            parts.append(
                f'<a href="{html.escape(_convert_href(href), quote=True)}">{html.escape(label)}</a>'
            )
        last_index = match.end()
    parts.append(_render_plain_fragment(text[last_index:]))
    return "".join(parts)


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def _is_table_separator(line: str) -> bool:
    if "|" not in line:
        return False
    cells = _split_table_row(line)
    return bool(cells) and all(bool(re.fullmatch(r":?-{3,}:?", cell or "")) for cell in cells)


def _strip_markdown(text: str) -> str:
    value = re.sub(r"```.*?```", " ", text, flags=re.S)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"^\s{0,3}#{1,6}\s+", "", value, flags=re.M)
    value = re.sub(r"^\s*[-*]\s+", "", value, flags=re.M)
    value = re.sub(r"^\s*\d+\.\s+", "", value, flags=re.M)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"\*([^*]+)\*", r"\1", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _extract_title(default_title: str, text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or default_title
    return default_title


def _extract_excerpt(text: str, *, limit: int = 180) -> str:
    plain = _strip_markdown(text)
    if len(plain) <= limit:
        return plain
    return plain[: limit - 3].rstrip() + "..."


def render_markdown(text: str) -> tuple[str, list[WikiHeading]]:
    lines = text.replace("\r\n", "\n").split("\n")
    parts: list[str] = []
    headings: list[WikiHeading] = []
    paragraph: list[str] = []
    list_kind: str | None = None
    code_lines: list[str] = []
    code_language = ""
    in_code = False
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            parts.append(f"<p>{_render_inline(' '.join(paragraph).strip())}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_kind
        if list_kind is not None:
            parts.append(f"</{list_kind}>")
            list_kind = None

    def flush_code() -> None:
        nonlocal in_code, code_language
        if in_code:
            language_class = f' class="language-{html.escape(code_language)}"' if code_language else ""
            code_text = "\n".join(code_lines)
            parts.append(f"<pre><code{language_class}>{html.escape(code_text)}</code></pre>")
            code_lines.clear()
            code_language = ""
            in_code = False

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if in_code:
            if stripped.startswith("```"):
                flush_code()
            else:
                code_lines.append(line)
            index += 1
            continue

        if stripped.startswith("```"):
            flush_paragraph()
            close_list()
            in_code = True
            code_language = stripped[3:].strip()
            code_lines.clear()
            index += 1
            continue

        if not stripped:
            flush_paragraph()
            close_list()
            index += 1
            continue

        if index + 1 < len(lines) and "|" in lines[index] and _is_table_separator(lines[index + 1]):
            flush_paragraph()
            close_list()
            header_cells = _split_table_row(lines[index])
            body_rows: list[list[str]] = []
            index += 2
            while index < len(lines):
                candidate = lines[index]
                if "|" not in candidate or not candidate.strip():
                    break
                body_rows.append(_split_table_row(candidate))
                index += 1
            parts.append("<table><thead><tr>")
            for cell in header_cells:
                parts.append(f"<th>{_render_inline(cell)}</th>")
            parts.append("</tr></thead><tbody>")
            for row in body_rows:
                parts.append("<tr>")
                for cell in row:
                    parts.append(f"<td>{_render_inline(cell)}</td>")
                parts.append("</tr>")
            parts.append("</tbody></table>")
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            flush_paragraph()
            close_list()
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            anchor = _slugify(heading_text)
            headings.append(WikiHeading(level=level, text=heading_text, anchor=anchor))
            parts.append(f'<h{level} id="{anchor}">{_render_inline(heading_text)}</h{level}>')
            index += 1
            continue

        unordered_match = re.match(r"^[-*]\s+(.*)$", stripped)
        ordered_match = re.match(r"^\d+\.\s+(.*)$", stripped)
        if unordered_match or ordered_match:
            flush_paragraph()
            next_list_kind = "ul" if unordered_match else "ol"
            if list_kind != next_list_kind:
                close_list()
                list_kind = next_list_kind
                parts.append(f"<{list_kind}>")
            item_text = unordered_match.group(1) if unordered_match else ordered_match.group(1)
            parts.append(f"<li>{_render_inline(item_text)}</li>")
            index += 1
            continue

        if stripped.startswith("> "):
            flush_paragraph()
            close_list()
            quote_lines = [stripped[2:].strip()]
            index += 1
            while index < len(lines) and lines[index].strip().startswith("> "):
                quote_lines.append(lines[index].strip()[2:].strip())
                index += 1
            parts.append(f"<blockquote><p>{_render_inline(' '.join(quote_lines))}</p></blockquote>")
            continue

        paragraph.append(stripped)
        index += 1

    flush_paragraph()
    close_list()
    flush_code()
    return "\n".join(parts), headings


class NovaWikiSiteBuilder:
    def __init__(self, source_dir: str | Path, output_dir: str | Path) -> None:
        self.source_dir = Path(source_dir).resolve(strict=False)
        self.output_dir = Path(output_dir).resolve(strict=False)

    def build(self) -> WikiBuildResult:
        if not self.source_dir.is_dir():
            raise FileNotFoundError(f"wiki source directory not found: {self.source_dir}")

        pages = self._load_pages()
        nav_sections = self._parse_sidebar()
        footer_html = self._load_footer_html()
        assets_dir = self.output_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        generated_files: list[str] = []
        search_index: list[dict[str, Any]] = []

        for page in pages:
            html_text = self._render_page(page, nav_sections, footer_html)
            output_path = self.output_dir / page.href
            output_path.write_text(html_text, encoding="utf-8")
            generated_files.append(str(output_path))
            if page.href == "Home.html":
                index_path = self.output_dir / "index.html"
                index_path.write_text(html_text, encoding="utf-8")
                generated_files.append(str(index_path))
            search_index.append(
                {
                    "title": page.title,
                    "href": page.href,
                    "excerpt": page.excerpt,
                    "headings": [heading.text for heading in page.headings if heading.level <= 3],
                    "content": page.search_text,
                }
            )

        (assets_dir / "wiki.css").write_text(_wiki_css(), encoding="utf-8")
        (assets_dir / "wiki.js").write_text(_wiki_js(), encoding="utf-8")
        (assets_dir / "search-index.json").write_text(
            json.dumps(search_index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        generated_files.extend(
            [
                str(assets_dir / "wiki.css"),
                str(assets_dir / "wiki.js"),
                str(assets_dir / "search-index.json"),
            ]
        )

        return WikiBuildResult(
            source_dir=str(self.source_dir),
            output_dir=str(self.output_dir),
            page_count=len(pages),
            home_page="Home.html",
            generated_files=generated_files,
            pages=[
                {
                    "title": page.title,
                    "href": page.href,
                    "source": str(page.source_path),
                    "excerpt": page.excerpt,
                }
                for page in pages
            ],
        )

    def _load_pages(self) -> list[WikiPage]:
        markdown_files = sorted(
            [path for path in self.source_dir.glob("*.md") if not path.name.startswith("_")],
            key=lambda item: (item.stem.lower() != "home", item.name.lower()),
        )
        pages: list[WikiPage] = []
        for path in markdown_files:
            text = path.read_text(encoding="utf-8")
            content_html, headings = render_markdown(text)
            pages.append(
                WikiPage(
                    title=_extract_title(path.stem, text),
                    source_path=path,
                    href=f"{path.stem}.html",
                    excerpt=_extract_excerpt(text),
                    headings=headings,
                    content_html=content_html,
                    search_text=_strip_markdown(text),
                )
            )
        return pages

    def _parse_sidebar(self) -> list[dict[str, Any]]:
        sidebar_path = self.source_dir / "_Sidebar.md"
        if not sidebar_path.is_file():
            return [
                {
                    "title": "Pages",
                    "items": [
                        {"label": path.stem, "href": f"{path.stem}.html"}
                        for path in sorted(self.source_dir.glob("*.md"))
                        if not path.name.startswith("_")
                    ],
                }
            ]

        sections: list[dict[str, Any]] = []
        current_section: dict[str, Any] | None = None
        for raw_line in sidebar_path.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            heading_match = re.match(r"^##\s+(.*)$", stripped)
            if heading_match:
                current_section = {"title": heading_match.group(1).strip(), "items": []}
                sections.append(current_section)
                continue
            link_match = re.match(r"^- \[([^\]]+)\]\(([^)]+)\)$", stripped)
            if link_match:
                if current_section is None:
                    current_section = {"title": "Pages", "items": []}
                    sections.append(current_section)
                current_section["items"].append(
                    {
                        "label": link_match.group(1).strip(),
                        "href": _convert_href(link_match.group(2).strip()),
                    }
                )
        return sections

    def _load_footer_html(self) -> str:
        footer_path = self.source_dir / "_Footer.md"
        if not footer_path.is_file():
            return "<p>Generated by Nova-shell wiki builder.</p>"
        footer_html, _ = render_markdown(footer_path.read_text(encoding="utf-8"))
        return footer_html

    def _render_page(self, page: WikiPage, nav_sections: list[dict[str, Any]], footer_html: str) -> str:
        nav_html = self._render_nav(nav_sections, page.href)
        toc_html = self._render_toc(page.headings)
        return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="generator" content="Nova-shell wiki builder">
  <title>{html.escape(page.title)} | Nova-shell Wiki</title>
  <link rel="stylesheet" href="assets/wiki.css">
</head>
<body>
  <div class="wiki-shell">
    <aside class="wiki-sidebar" data-sidebar>
      <div class="wiki-brand">
        <a href="Home.html">Nova-shell Wiki</a>
        <p>HTML documentation for the Nova-shell platform.</p>
      </div>
      <label class="wiki-search">
        <span>Search</span>
        <input type="search" placeholder="Find pages, classes, methods..." data-wiki-search>
      </label>
      <div class="wiki-search-results" data-search-results></div>
      <nav class="wiki-nav">
        {nav_html}
      </nav>
    </aside>
    <main class="wiki-main">
      <header class="wiki-header">
        <button type="button" class="wiki-nav-toggle" data-nav-toggle>Menu</button>
        <div class="wiki-header-copy">
          <span class="wiki-kicker">Nova-shell Documentation</span>
          <h1>{html.escape(page.title)}</h1>
          <p>Source: {html.escape(page.source_path.name)}</p>
        </div>
      </header>
      <div class="wiki-layout">
        <article class="wiki-article">
          {page.content_html}
        </article>
        <aside class="wiki-toc">
          {toc_html}
        </aside>
      </div>
      <footer class="wiki-footer">
        {footer_html}
      </footer>
    </main>
  </div>
  <script>
    window.NOVA_WIKI = {{
      currentPage: {json.dumps(page.href)},
      searchIndex: "assets/search-index.json"
    }};
  </script>
  <script src="assets/wiki.js" defer></script>
</body>
</html>
"""

    def _render_nav(self, nav_sections: list[dict[str, Any]], current_href: str) -> str:
        parts: list[str] = []
        for section in nav_sections:
            parts.append('<section class="wiki-nav-section">')
            parts.append(f"<h2>{html.escape(str(section.get('title') or 'Pages'))}</h2>")
            parts.append("<ul>")
            for item in section.get("items", []):
                href = str(item.get("href") or "")
                active_class = " active" if href == current_href else ""
                parts.append(
                    f'<li><a class="wiki-nav-link{active_class}" data-nav-href="{html.escape(href, quote=True)}" '
                    f'href="{html.escape(href, quote=True)}">{html.escape(str(item.get("label") or href))}</a></li>'
                )
            parts.append("</ul></section>")
        return "\n".join(parts)

    def _render_toc(self, headings: list[WikiHeading]) -> str:
        candidates = [heading for heading in headings if heading.level in {2, 3}]
        if not candidates:
            return "<div class=\"wiki-toc-empty\">No subheadings on this page.</div>"
        parts = ["<div class=\"wiki-toc-card\"><h2>On this page</h2><ul>"]
        for heading in candidates:
            indent = " level-3" if heading.level == 3 else ""
            parts.append(
                f'<li class="wiki-toc-link{indent}"><a href="#{html.escape(heading.anchor, quote=True)}">{html.escape(heading.text)}</a></li>'
            )
        parts.append("</ul></div>")
        return "\n".join(parts)


class NovaWikiSiteServer:
    def __init__(self, output_dir: str | Path, *, host: str = "127.0.0.1", port: int = 8767) -> None:
        self.output_dir = Path(output_dir).resolve(strict=False)
        self.host = host
        self.port = port
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> dict[str, Any]:
        if self._server is not None:
            return self.status()

        directory = str(self.output_dir)

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, directory=directory, **kwargs)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

        self._server = http.server.ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        if self._server is None:
            return self.status()
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        with contextlib.suppress(Exception):
            server.shutdown()
        with contextlib.suppress(Exception):
            server.server_close()
        if thread is not None:
            thread.join(timeout=2.0)
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "running": self._server is not None,
            "host": self.host,
            "port": self.port,
            "output_dir": str(self.output_dir),
            "url": self.url(),
        }

    def url(self, page: str = "Home.html") -> str:
        normalized = page.lstrip("/") if page else "Home.html"
        if normalized == "index.html":
            normalized = ""
        suffix = f"/{normalized}" if normalized else "/"
        return f"http://{self.host}:{self.port}{suffix}"


def _wiki_css() -> str:
    return """
:root {
  --bg: #eef3f1;
  --panel: rgba(255, 255, 255, 0.88);
  --panel-strong: #ffffff;
  --line: rgba(24, 58, 53, 0.12);
  --text: #183a35;
  --muted: #53706a;
  --accent: #0f766e;
  --accent-soft: rgba(15, 118, 110, 0.12);
  --accent-2: #1d4ed8;
  --shadow: 0 18px 55px rgba(24, 58, 53, 0.12);
  --radius: 22px;
  --mono: "IBM Plex Mono", "Cascadia Code", "Consolas", monospace;
  --sans: "IBM Plex Sans", "Segoe UI", sans-serif;
}

* { box-sizing: border-box; }

html, body {
  margin: 0;
  min-height: 100%;
  background:
    radial-gradient(circle at top left, rgba(29, 78, 216, 0.10), transparent 28%),
    radial-gradient(circle at bottom right, rgba(15, 118, 110, 0.14), transparent 34%),
    linear-gradient(180deg, #f8fbfa 0%, var(--bg) 100%);
  color: var(--text);
  font-family: var(--sans);
}

body { min-height: 100vh; }

.wiki-shell {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  min-height: 100vh;
}

.wiki-sidebar {
  position: sticky;
  top: 0;
  align-self: start;
  height: 100vh;
  overflow: auto;
  padding: 28px 22px;
  background: rgba(13, 43, 39, 0.92);
  color: #edf7f4;
  border-right: 1px solid rgba(255, 255, 255, 0.08);
}

.wiki-brand a {
  color: #ffffff;
  text-decoration: none;
  font-size: 1.45rem;
  font-weight: 700;
  letter-spacing: -0.03em;
}

.wiki-brand p {
  margin: 10px 0 0;
  color: rgba(237, 247, 244, 0.78);
  line-height: 1.55;
}

.wiki-search {
  display: block;
  margin: 24px 0 18px;
  font-size: 0.82rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(237, 247, 244, 0.7);
}

.wiki-search input {
  width: 100%;
  margin-top: 8px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.08);
  color: #ffffff;
  border-radius: 14px;
  padding: 12px 14px;
  outline: none;
}

.wiki-search-results {
  display: none;
  margin-bottom: 16px;
  border-radius: 16px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.06);
}

.wiki-search-results.visible { display: block; }

.wiki-search-results a {
  display: block;
  padding: 12px 14px;
  text-decoration: none;
  color: #edf7f4;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.wiki-search-results a:first-child { border-top: 0; }

.wiki-search-results span {
  display: block;
  margin-top: 4px;
  color: rgba(237, 247, 244, 0.74);
  font-size: 0.9rem;
}

.wiki-nav-section + .wiki-nav-section { margin-top: 22px; }

.wiki-nav-section h2 {
  margin: 0 0 10px;
  font-size: 0.82rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(237, 247, 244, 0.62);
}

.wiki-nav-section ul {
  margin: 0;
  padding: 0;
  list-style: none;
}

.wiki-nav-link {
  display: block;
  padding: 9px 12px;
  border-radius: 12px;
  color: #edf7f4;
  text-decoration: none;
  transition: background 120ms ease, transform 120ms ease;
}

.wiki-nav-link:hover,
.wiki-nav-link.active {
  background: rgba(255, 255, 255, 0.10);
  transform: translateX(2px);
}

.wiki-main { padding: 28px; }

.wiki-header {
  display: flex;
  align-items: start;
  gap: 18px;
  margin-bottom: 22px;
}

.wiki-nav-toggle {
  display: none;
  border: 0;
  background: var(--panel-strong);
  color: var(--text);
  box-shadow: var(--shadow);
  border-radius: 14px;
  padding: 11px 14px;
  font: inherit;
  cursor: pointer;
}

.wiki-header-copy {
  padding: 28px 30px;
  width: 100%;
  border-radius: 28px;
  background: linear-gradient(140deg, rgba(15, 118, 110, 0.12), rgba(29, 78, 216, 0.08));
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
}

.wiki-kicker {
  display: inline-block;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: var(--accent);
}

.wiki-header h1 {
  margin: 10px 0 8px;
  font-size: clamp(2rem, 3vw, 3rem);
  line-height: 1.05;
  letter-spacing: -0.04em;
}

.wiki-header p {
  margin: 0;
  color: var(--muted);
}

.wiki-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 260px;
  gap: 22px;
  align-items: start;
}

.wiki-article,
.wiki-toc,
.wiki-footer {
  border-radius: var(--radius);
  background: var(--panel);
  backdrop-filter: blur(12px);
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
}

.wiki-article { padding: 34px 34px 40px; }

.wiki-article h1,
.wiki-article h2,
.wiki-article h3,
.wiki-article h4 {
  letter-spacing: -0.03em;
  margin: 1.7em 0 0.55em;
}

.wiki-article h1:first-child { margin-top: 0; }

.wiki-article p,
.wiki-article li,
.wiki-article td,
.wiki-article th,
.wiki-article blockquote { line-height: 1.72; }

.wiki-article a,
.wiki-toc a,
.wiki-footer a { color: var(--accent-2); }

.wiki-article code,
.wiki-article pre { font-family: var(--mono); }

.wiki-article code {
  padding: 0.18em 0.38em;
  background: rgba(15, 118, 110, 0.10);
  border-radius: 8px;
}

.wiki-article pre {
  overflow: auto;
  padding: 18px;
  border-radius: 18px;
  background: #13211f;
  color: #eef7f4;
}

.wiki-article table {
  width: 100%;
  border-collapse: collapse;
  margin: 18px 0 26px;
  border-radius: 18px;
  overflow: hidden;
}

.wiki-article th,
.wiki-article td {
  border: 1px solid rgba(24, 58, 53, 0.12);
  padding: 12px 14px;
  vertical-align: top;
}

.wiki-article th {
  background: rgba(15, 118, 110, 0.10);
  text-align: left;
}

.wiki-article ul,
.wiki-article ol { padding-left: 1.4rem; }

.wiki-article blockquote {
  margin: 18px 0;
  padding: 12px 18px;
  border-left: 4px solid var(--accent);
  background: var(--accent-soft);
  border-radius: 0 16px 16px 0;
}

.wiki-toc {
  position: sticky;
  top: 28px;
  padding: 20px;
}

.wiki-toc-card h2,
.wiki-toc-empty {
  margin: 0;
  font-size: 0.95rem;
}

.wiki-toc-card ul {
  margin: 16px 0 0;
  padding: 0;
  list-style: none;
}

.wiki-toc-link { margin: 0 0 10px; }
.wiki-toc-link.level-3 { margin-left: 16px; }

.wiki-footer {
  margin-top: 22px;
  padding: 22px 24px;
}

@media (max-width: 1100px) {
  .wiki-layout { grid-template-columns: 1fr; }
  .wiki-toc { position: static; }
}

@media (max-width: 900px) {
  .wiki-shell { grid-template-columns: 1fr; }

  .wiki-sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    width: min(84vw, 320px);
    transform: translateX(-100%);
    transition: transform 180ms ease;
    z-index: 40;
  }

  .wiki-sidebar.open { transform: translateX(0); }
  .wiki-main { padding: 18px; }

  .wiki-nav-toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .wiki-article { padding: 24px 22px 28px; }
}
"""


def _wiki_js() -> str:
    return """
(function () {
  const config = window.NOVA_WIKI || {};
  const searchInput = document.querySelector("[data-wiki-search]");
  const searchResults = document.querySelector("[data-search-results]");
  const sidebar = document.querySelector("[data-sidebar]");
  const toggle = document.querySelector("[data-nav-toggle]");

  if (toggle && sidebar) {
    toggle.addEventListener("click", function () {
      sidebar.classList.toggle("open");
    });
  }

  if (!searchInput || !searchResults || !config.searchIndex) {
    return;
  }

  fetch(config.searchIndex)
    .then(function (response) { return response.json(); })
    .then(function (pages) {
      const renderResults = function (query) {
        const normalized = query.trim().toLowerCase();
        if (!normalized) {
          searchResults.classList.remove("visible");
          searchResults.innerHTML = "";
          return;
        }

        const matches = pages
          .filter(function (page) {
            const haystack = [page.title, page.excerpt, page.content].join(" ").toLowerCase();
            return haystack.indexOf(normalized) >= 0;
          })
          .slice(0, 8);

        searchResults.classList.add("visible");
        searchResults.innerHTML = matches.length
          ? matches.map(function (page) {
              return "<a href=\\"" + page.href + "\\"><strong>" + page.title + "</strong><span>" + (page.excerpt || "") + "</span></a>";
            }).join("")
          : "<a href=\\"#\\"><strong>No matches</strong><span>Try another keyword.</span></a>";
      };

      searchInput.addEventListener("input", function () {
        renderResults(searchInput.value);
      });
    })
    .catch(function () {
      searchResults.classList.remove("visible");
      searchResults.innerHTML = "";
    });
})();
"""
