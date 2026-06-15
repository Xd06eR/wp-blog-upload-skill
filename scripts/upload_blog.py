"""Orchestrator: parse a markdown brief and commit it as a WordPress draft.

Pure upload. No preview, no audit log, no images. The brief is the
finished body prose; this module turns it into editor-specific markup
and POSTs to WP REST as `status=draft`. SEO meta (Yoast / RankMath) is
left for the writer to fill manually -- those plugins do not support
REST.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import adapters
from .tools import parse_md
from .tools.client_config import ClientConfig
from .tools.parse_md import Block, Brief, ParsedDoc
from .tools.wp_client import WPClient, WPCredentials

__all__ = ["ClientConfig", "UploadResult", "upload_blog", "upload_prepared"]


_ALLOWED_BLOCK_KINDS = {"h1", "h2", "h3", "h4", "paragraph", "list", "table"}


@dataclass
class UploadResult:
    title: str
    post_id: int
    post_url: str
    edit_url: str
    brand: str = ""


def upload_blog(
    doc_path: str | Path,
    client_cfg: ClientConfig,
    *,
    brand: str | None = None,
) -> UploadResult:
    """Parse the markdown brief, render content, create a WP draft."""
    doc = parse_md.parse(doc_path, brand=brand)
    return _post_parsed_doc(doc, client_cfg)


def upload_prepared(payload: dict, client_cfg: ClientConfig) -> UploadResult:
    """Upload from an agent-emitted ParsedDoc payload.

    Use when the markdown parser cannot handle the brief format directly
    (alien table shapes, body-in-cell, missing brand header). The agent
    extracts the brief into the JSON shape below and the CLI handles the
    deterministic render + POST.

    Required shape:
        {
          "brand": "ExampleBrand",
          "title": "...",
          "brief": {
            "page_url": "...",
            "h1": "...",
            "meta_title": "...",
            "meta_description": "...",
            "word_count": "500 words",
            "keywords": ["keyword one", "keyword two"],
            "target_audience": "..."
          },
          "body": [
            {"kind": "h2", "text": "..."},
            {"kind": "h3", "text": "..."},
            {"kind": "paragraph", "text": "..."},
            {"kind": "list", "items": ["...", "..."]}
          ]
        }

    Text fields may contain inline HTML (`<a>`, `<strong>`); raw text is
    HTML-escaped by the adapters.
    """
    doc = _payload_to_parsed_doc(payload)
    return _post_parsed_doc(doc, client_cfg)


def _payload_to_parsed_doc(payload: dict) -> ParsedDoc:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    title = str(payload.get("title", "")).strip()
    if not title:
        raise ValueError("payload.title is required (used as WP post title)")

    brief_in = payload.get("brief") or {}
    if not isinstance(brief_in, dict):
        raise ValueError("payload.brief must be an object")

    keywords_in = brief_in.get("keywords") or []
    if not isinstance(keywords_in, list):
        raise ValueError("payload.brief.keywords must be an array")

    brief = Brief(
        page_url=str(brief_in.get("page_url", "")).strip(),
        h1=str(brief_in.get("h1", "")).strip(),
        meta_title=str(brief_in.get("meta_title", "")).strip(),
        meta_description=str(brief_in.get("meta_description", "")).strip(),
        word_count=str(brief_in.get("word_count", "")).strip(),
        keywords=[str(k).strip() for k in keywords_in if str(k).strip()],
        target_audience=str(brief_in.get("target_audience", "")).strip(),
    )

    body_in = payload.get("body") or []
    if not isinstance(body_in, list):
        raise ValueError("payload.body must be an array")

    blocks: list[Block] = []
    for i, block_in in enumerate(body_in):
        if not isinstance(block_in, dict):
            raise ValueError(f"payload.body[{i}] must be an object")
        kind = str(block_in.get("kind", "")).strip().lower()
        if kind not in _ALLOWED_BLOCK_KINDS:
            raise ValueError(
                f"payload.body[{i}].kind must be one of {sorted(_ALLOWED_BLOCK_KINDS)}, got '{kind}'"
            )
        if kind == "list":
            items = block_in.get("items") or []
            if not isinstance(items, list):
                raise ValueError(f"payload.body[{i}].items must be an array of strings")
            blocks.append(Block(kind="list", items=[str(x) for x in items if str(x).strip()]))
        else:
            blocks.append(Block(kind=kind, text=str(block_in.get("text", "")).strip()))

    return ParsedDoc(
        brief=brief,
        body=blocks,
        title=title,
        brand=str(payload.get("brand", "")).strip(),
    )


def _post_parsed_doc(doc: ParsedDoc, client_cfg: ClientConfig) -> UploadResult:
    title = client_cfg.title_template.format(h1=doc.title or "Untitled")

    creds = WPCredentials.load(client_cfg.wp_credentials_path)
    wp = WPClient(creds)

    rendered = adapters.get(client_cfg.editor)(doc)
    content, extra_meta = _split_content(client_cfg.editor, rendered)

    payload: dict[str, Any] = {
        "title": title,
        "content": content,
        "status": "draft",
    }

    if client_cfg.default_category:
        cat_id = wp.find_category_id(client_cfg.default_category)
        if cat_id:
            payload["categories"] = [cat_id]

    tag_names = list(client_cfg.default_tags) + doc.brief.keywords
    if tag_names:
        payload["tags"] = [wp.find_or_create_tag(t) for t in tag_names if t]

    if extra_meta:
        payload["meta"] = extra_meta

    post = wp.create_post(payload)

    return UploadResult(
        title=title,
        post_id=post["id"],
        post_url=post.get("link", ""),
        edit_url=f"{creds.site_base}/wp-admin/post.php?post={post['id']}&action=edit",
        brand=doc.brand,
    )


def _split_content(editor: str, rendered: str) -> tuple[str, dict[str, Any]]:
    """Elementor returns a JSON envelope with content + meta. Others return raw."""
    if editor.strip().lower() != "elementor":
        return rendered, {}
    try:
        envelope = json.loads(rendered)
    except json.JSONDecodeError:
        return rendered, {}
    return envelope.get("content", ""), envelope.get("meta", {}) or {}
