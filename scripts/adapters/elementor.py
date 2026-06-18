"""Elementor adapter -- writes `_elementor_data` meta + plain-HTML fallback.

Elementor stores body as a JSON tree in post meta `_elementor_data`. Tree =
sections containing columns containing widgets. We generate one section per
body block. Valid for Elementor 3.0+.

Returns a JSON string:
    {"content": "<plain html fallback>",
     "meta": {"_elementor_data": "[...]",
              "_elementor_edit_mode": "builder",
              "_elementor_template_type": "wp-post",
              "_elementor_version": "3.0.0"}}

upload_blog.py unpacks this dict into the right WP REST fields.
"""

from __future__ import annotations

import json
import uuid

from ..tools.parse_md import Block, ParsedDoc
from ._escape import build_todo_meta, escape_inline as _safe


def render(doc: ParsedDoc) -> str:
    """Return JSON string with content + meta for Elementor posts."""
    elementor_sections: list[dict] = []
    fallback_html: list[str] = [_todo_meta_comment(doc)]

    for block in doc.body:
        widget = _block_to_widget(block)
        if widget:
            elementor_sections.append(_wrap_in_section(widget))
        fallback = _block_to_html(block)
        if fallback:
            fallback_html.append(fallback)

    payload = {
        "content": "\n\n".join(fallback_html),
        "meta": {
            "_elementor_data": json.dumps(elementor_sections),
            "_elementor_edit_mode": "builder",
            "_elementor_template_type": "wp-post",
            "_elementor_version": "3.0.0",
        },
    }
    return json.dumps(payload)


def _wrap_in_section(widget: dict) -> dict:
    return {
        "id": _eid(), "elType": "section",
        "settings": {}, "isInner": False,
        "elements": [{
            "id": _eid(), "elType": "column",
            "settings": {"_column_size": 100, "_inline_size": None},
            "elements": [widget], "isInner": False,
        }],
    }


def _block_to_widget(block: Block) -> dict | None:
    if block.kind in ("h1", "h2", "h3", "h4"):
        size = "h2" if block.kind == "h1" else block.kind
        return {
            "id": _eid(), "elType": "widget",
            "widgetType": "heading", "settings": {
                # Keep inline <strong>/<a> like the other adapters instead of
                # stripping every tag; the heading widget renders inline HTML.
                "title": _safe(block.text),
                "header_size": size,
                "align": "left",
            },
            "elements": [], "isInner": False,
        }
    if block.kind == "paragraph":
        return {
            "id": _eid(), "elType": "widget",
            "widgetType": "text-editor", "settings": {
                "editor": f"<p>{_safe(block.text)}</p>",
            },
            "elements": [], "isInner": False,
        }
    if block.kind == "list":
        items_html = "".join(f"<li>{_safe(i)}</li>" for i in block.items)
        return {
            "id": _eid(), "elType": "widget",
            "widgetType": "text-editor", "settings": {
                "editor": f"<ul>{items_html}</ul>",
            },
            "elements": [], "isInner": False,
        }
    if block.kind == "table":
        table_html = _table_html(block.rows)
        return {
            "id": _eid(), "elType": "widget",
            "widgetType": "text-editor", "settings": {"editor": table_html},
            "elements": [], "isInner": False,
        }
    return None


def _table_html(rows: list[list[str]]) -> str:
    if not rows:
        return ""

    def tr(cells: list[str], tag: str) -> str:
        return "<tr>" + "".join(f"<{tag}>{_safe(c)}</{tag}>" for c in cells) + "</tr>"

    head = f"<thead>{tr(rows[0], 'th')}</thead>"
    body_rows = "".join(tr(r, "td") for r in rows[1:])
    body = f"<tbody>{body_rows}</tbody>" if body_rows else ""
    return f"<table>{head}{body}</table>"


def _block_to_html(block: Block) -> str:
    if block.kind in ("h1", "h2", "h3", "h4"):
        level = 2 if block.kind == "h1" else int(block.kind[1])
        return f"<h{level}>{_safe(block.text)}</h{level}>"
    if block.kind == "paragraph":
        return f"<p>{_safe(block.text)}</p>"
    if block.kind == "list":
        items = "".join(f"<li>{_safe(i)}</li>" for i in block.items)
        return f"<ul>{items}</ul>"
    if block.kind == "table":
        return _table_html(block.rows)
    return ""


def _todo_meta_comment(doc: ParsedDoc) -> str:
    return build_todo_meta(
        doc.brief,
        extra_lines=("- Open in Elementor editor to verify layout (fallback is plain HTML).",),
    )


def _eid() -> str:
    return uuid.uuid4().hex[:7]
