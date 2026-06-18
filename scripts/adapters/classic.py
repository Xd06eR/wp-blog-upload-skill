"""Classic editor adapter -- raw HTML in the post `content` field."""

from __future__ import annotations

from ..tools.parse_md import Block, ParsedDoc
from ._escape import _escape_attr, build_todo_meta, escape_inline


def render(doc: ParsedDoc) -> str:
    """Return raw HTML for the post content field."""
    parts: list[str] = [_todo_meta_comment(doc)]
    for block in doc.body:
        rendered = _render_block(block)
        if rendered:
            parts.append(rendered)
    return "\n\n".join(p for p in parts if p)


def _render_block(block: Block) -> str:
    if block.kind in ("h1", "h2", "h3", "h4"):
        level = 2 if block.kind == "h1" else int(block.kind[1])
        return f"<h{level}>{escape_inline(block.text)}</h{level}>"
    if block.kind == "paragraph":
        return f"<p>{escape_inline(block.text)}</p>"
    if block.kind == "list":
        items = "".join(f"<li>{escape_inline(i)}</li>" for i in block.items)
        return f"<ul>{items}</ul>"
    if block.kind == "table":
        return _table_html(block.rows)
    if block.kind == "image":
        return _image_html(block)
    return ""


def _image_html(block: Block) -> str:
    # Skip an unresolved image rather than emit a broken <img> with empty src.
    if not block.media_url:
        return ""
    src = _escape_attr(block.media_url)
    alt = _escape_attr(block.alt)
    cls = f' class="wp-image-{block.media_id}"' if block.media_id else ""
    return f'<figure><img src="{src}" alt="{alt}"{cls}/></figure>'


def _table_html(rows: list[list[str]]) -> str:
    if not rows:
        return ""

    def tr(cells: list[str], tag: str) -> str:
        return "<tr>" + "".join(f"<{tag}>{escape_inline(c)}</{tag}>" for c in cells) + "</tr>"

    head = f"<thead>{tr(rows[0], 'th')}</thead>"
    body_rows = "".join(tr(r, "td") for r in rows[1:])
    body = f"<tbody>{body_rows}</tbody>" if body_rows else ""
    return f"<table>{head}{body}</table>"


def _todo_meta_comment(doc: ParsedDoc) -> str:
    return build_todo_meta(doc.brief)
