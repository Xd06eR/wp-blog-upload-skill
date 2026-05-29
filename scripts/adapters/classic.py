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
    return ""


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
