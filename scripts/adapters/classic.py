"""Classic editor adapter -- raw HTML in the post `content` field."""

from __future__ import annotations

import html
import re

from ..tools.parse_md import Block, ParsedDoc


def render(doc: ParsedDoc) -> str:
    """Return raw HTML for the post content field."""
    parts: list[str] = [_todo_meta_comment(doc)]
    for block in doc.body:
        rendered = _render_block(block)
        if rendered:
            parts.append(rendered)
    return "\n\n".join(p for p in parts if p)


def _contains_html(text: str) -> bool:
    return bool(re.search(r"<[a-zA-Z][^>]*>", text))


def _render_block(block: Block) -> str:
    if block.kind in ("h1", "h2", "h3", "h4"):
        level = 2 if block.kind == "h1" else int(block.kind[1])
        safe = block.text if _contains_html(block.text) else html.escape(block.text)
        return f"<h{level}>{safe}</h{level}>"
    if block.kind == "paragraph":
        safe = block.text if _contains_html(block.text) else html.escape(block.text)
        return f"<p>{safe}</p>"
    if block.kind == "list":
        items = "".join(
            f"<li>{i if _contains_html(i) else html.escape(i)}</li>"
            for i in block.items
        )
        return f"<ul>{items}</ul>"
    if block.kind == "table":
        return _table_html(block.rows)
    return ""


def _table_html(rows: list[list[str]]) -> str:
    if not rows:
        return ""

    def cell(text: str) -> str:
        return text if _contains_html(text) else html.escape(text)

    def tr(cells: list[str], tag: str) -> str:
        return "<tr>" + "".join(f"<{tag}>{cell(c)}</{tag}>" for c in cells) + "</tr>"

    head = f"<thead>{tr(rows[0], 'th')}</thead>"
    body_rows = "".join(tr(r, "td") for r in rows[1:])
    body = f"<tbody>{body_rows}</tbody>" if body_rows else ""
    return f"<table>{head}{body}</table>"


def _todo_meta_comment(doc: ParsedDoc) -> str:
    keywords = ", ".join(doc.brief.keywords) if doc.brief.keywords else "(none)"
    return (
        "<!-- TODO META FOR HUMAN:\n"
        "  - Fill SEO title + meta description in Yoast / RankMath / AIOSEO (no REST API)\n"
        f"  - Meta title (suggested): {doc.brief.meta_title or '(none)'}\n"
        f"  - Meta description (suggested): {doc.brief.meta_description or '(none)'}\n"
        f"  - Target URL: {doc.brief.page_url or '(not specified)'}\n"
        f"  - Keywords: {keywords}\n"
        "-->"
    )
