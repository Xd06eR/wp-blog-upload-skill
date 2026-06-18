"""Render the parsed AST to Gutenberg block markup.

Gutenberg posts are HTML wrapped in `<!-- wp:* -->` comments. Block types
used here: heading, paragraph, list. A hidden `<!-- TODO META -->` comment
is injected at the top so the writer remembers to fill in Yoast / RankMath
fields after the upload (those plugins do NOT support REST).
"""

from __future__ import annotations

from ..tools.parse_md import Block, ParsedDoc
from ._escape import escape_inline


def render(doc: ParsedDoc) -> str:
    """Return the post `content` field — Gutenberg block markup."""
    parts: list[str] = [_todo_meta_comment(doc)]
    for block in doc.body:
        rendered = _render_block(block)
        if rendered:
            parts.append(rendered)
    return "\n\n".join(p for p in parts if p)


def _render_block(block: Block) -> str:
    if block.kind in ("h1", "h2", "h3", "h4"):
        level = int(block.kind[1])
        return _heading_block(block.text, level)
    if block.kind == "paragraph":
        return _paragraph_block(block.text)
    if block.kind == "list":
        return _list_block(block.items)
    if block.kind == "table":
        return _table_block(block.rows)
    return ""


def _heading_block(text: str, level: int) -> str:
    safe = escape_inline(text)
    if level == 1:
        level = 2
    attrs = "" if level == 2 else f' {{"level":{level}}}'
    return (
        f"<!-- wp:heading{attrs} -->\n"
        f"<h{level}>{safe}</h{level}>\n"
        f"<!-- /wp:heading -->"
    )


def _paragraph_block(text: str) -> str:
    return f"<!-- wp:paragraph -->\n<p>{escape_inline(text)}</p>\n<!-- /wp:paragraph -->"


def _list_block(items: list[str]) -> str:
    li = "\n".join(f"<li>{escape_inline(i)}</li>" for i in items)
    return (
        "<!-- wp:list -->\n"
        f"<ul>\n{li}\n</ul>\n"
        "<!-- /wp:list -->"
    )


def _cell(text: str) -> str:
    return escape_inline(text)


def _table_block(rows: list[list[str]]) -> str:
    if not rows:
        return ""

    def tr(cells: list[str], tag: str) -> str:
        return "<tr>" + "".join(f"<{tag}>{_cell(c)}</{tag}>" for c in cells) + "</tr>"

    head = f"<thead>{tr(rows[0], 'th')}</thead>" if rows else ""
    body_rows = "".join(tr(r, "td") for r in rows[1:])
    body = f"<tbody>{body_rows}</tbody>" if body_rows else ""
    return (
        "<!-- wp:table -->\n"
        f'<figure class="wp-block-table"><table>{head}{body}</table></figure>\n'
        "<!-- /wp:table -->"
    )


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
