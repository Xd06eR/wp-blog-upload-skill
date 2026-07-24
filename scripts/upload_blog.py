"""Orchestrator: commit a brief (or a finished HTML blog) as a WordPress draft.

Pure upload. No preview, no audit log. Three entry points: `upload_blog` parses
a `.docx`/`.md` brief and renders it into editor-specific markup;
`upload_prepared` renders the same way from a pre-parsed JSON `ParsedDoc`
payload (no file parse); `upload_html` posts a finished `.html` blog verbatim
(no parse, no render). All POST to WP REST as `status=draft`. SEO meta (Yoast /
RankMath) is left for the writer to fill manually -- those plugins do not
support REST.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import adapters
from .tools.client_config import ClientConfig
from .tools.parse_md import Block, Brief, ParsedDoc
from .tools.wp_client import WPClient, WPCredentials, WPError

__all__ = ["ClientConfig", "UploadResult", "upload_blog", "upload_html", "upload_prepared"]


_ALLOWED_BLOCK_KINDS = {"h1", "h2", "h3", "h4", "paragraph", "list", "table", "image"}


@dataclass
class UploadResult:
    title: str
    post_id: int
    post_url: str
    edit_url: str
    brand: str = ""
    warnings: list[str] = field(default_factory=list)
    media: list[dict] = field(default_factory=list)



def upload_blog(
    doc_path: str | Path,
    client_cfg: ClientConfig,
    *,
    brand: str | None = None,
    media_dir: str | Path | None = None,
) -> UploadResult:
    """Parse the brief (.docx or .md, auto-detected), render, create a WP draft.

    When `media_dir` is given, every image file in that folder is uploaded and
    appended to the body (name-sorted); the first becomes the featured image.
    """
    from .tools.intake import parser_for
    doc = parser_for(doc_path).parse(doc_path, brand=brand)
    if media_dir:
        doc = replace(doc, body=[*doc.body, *_media_dir_blocks(media_dir)])
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
            {"kind": "list", "items": ["...", "..."]},
            {"kind": "table", "rows": [["...", "..."], ["...", "..."]]},
            {"kind": "image", "src": "/abs/path.jpg", "alt": "..."}
          ]
        }

    Text fields may contain inline HTML (`<a>`, `<strong>`); raw text is
    HTML-escaped by the adapters.
    """
    doc = _payload_to_parsed_doc(payload)
    return _post_parsed_doc(doc, client_cfg)


_H1_RE = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_BODY_RE = re.compile(r"<body\b[^>]*>(.*?)</body>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _extract_title_and_body(
    html: str, override_title: str | None, fallback_title: str
) -> tuple[str, str]:
    """Lift the first <h1> into the title and drop that element from the body.

    WordPress renders the post title as the page H1, so keeping the source <h1>
    in the body would double-title the page. Everything else is left byte-for-
    byte (TOC anchors, heading ids, inline links all survive). A full-document
    paste is reduced to its <body> inner first so <head>/chrome never reaches WP.
    """
    # ponytail: single-<body> assumption; a multi-body document isn't expected.
    body_match = _BODY_RE.search(html)
    if body_match:
        html = body_match.group(1)

    h1_text = ""
    m = _H1_RE.search(html)
    if m:
        h1_text = _TAG_RE.sub("", m.group(1)).strip()
        html = html[: m.start()] + html[m.end() :]

    title = (override_title or h1_text or fallback_title or "Untitled").strip()
    return title, html


def _upload_featured(
    media_dir: str | Path, wp: WPClient, warnings: list[str]
) -> tuple[int, list[dict]]:
    """Upload every image in `media_dir`; set the first as the featured image.

    Unlike the .docx/.md path (`_resolve_media`), this does NOT append image
    markup to the body — a finished HTML already places its own images, so the
    only gap WordPress has is the featured thumbnail. Returns (featured_id,
    media_list). A per-image failure is a warning, not a fatal error.
    """
    featured = 0
    media: list[dict] = []
    for block in _media_dir_blocks(media_dir):
        try:
            up = wp.upload_media(block.src, alt_text=block.alt)
        except (WPError, OSError) as e:
            warnings.append(f"Image upload failed for {Path(block.src).name}: {e}")
            continue
        media_id = int(up.get("id", 0) or 0)
        if media_id:
            media.append({"id": media_id, "url": up.get("source_url", "")})
            if not featured:
                featured = media_id
    return featured, media


def upload_html(
    html: str,
    client_cfg: ClientConfig,
    *,
    title: str | None = None,
    fallback_title: str = "Untitled",
    media_dir: str | Path | None = None,
) -> UploadResult:
    """Upload a finished HTML blog verbatim as a WP draft — no parse, no render.

    The HTML is the completed, cleaned body: it goes to WP `content` byte-for-
    byte, so TOC anchor links and heading ids are preserved (the parse+adapter
    path would re-clean and drop them). The first <h1> becomes the post title
    and is removed from the body; pass `title` to override. `media_dir` uploads
    images and sets the first as the featured image WITHOUT touching the body.
    """
    post_title, body = _extract_title_and_body(html, title, fallback_title)
    if not body.strip():
        raise ValueError(
            "HTML brief produced an empty body — refusing to post a blank draft."
        )

    creds = WPCredentials.load(client_cfg.wp_credentials_path)
    wp = WPClient(creds)

    warnings: list[str] = []
    featured_media, media = (
        _upload_featured(media_dir, wp, warnings) if media_dir else (0, [])
    )

    payload: dict[str, Any] = {
        "title": _apply_title_template(client_cfg.title_template, post_title),
        "content": body,
        "status": "draft",
    }
    if featured_media:
        payload["featured_media"] = featured_media
    if client_cfg.default_category:
        cat_id = wp.find_category_id(client_cfg.default_category)
        if cat_id:
            payload["categories"] = [cat_id]
    tag_ids = [wp.find_or_create_tag(t) for t in client_cfg.default_tags if t]
    if tag_ids:
        payload["tags"] = tag_ids

    post = wp.create_post(payload)
    return UploadResult(
        title=payload["title"],
        post_id=post["id"],
        post_url=post.get("link", ""),
        edit_url=f"{creds.site_base}/wp-admin/post.php?post={post['id']}&action=edit",
        warnings=warnings,
        media=media,
    )


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
        elif kind == "image":
            src = str(block_in.get("src", "")).strip()
            if not src:
                raise ValueError(f"payload.body[{i}] image block requires 'src' (local file path)")
            blocks.append(Block(kind="image", src=src, alt=str(block_in.get("alt", "")).strip()))
        elif kind == "table":
            rows_in = block_in.get("rows")
            if not isinstance(rows_in, list) or not all(isinstance(r, list) for r in rows_in):
                raise ValueError(
                    f"payload.body[{i}] table block requires 'rows' (an array of row arrays)"
                )
            blocks.append(Block(kind="table", rows=[[str(c) for c in row] for row in rows_in]))
        else:
            blocks.append(Block(kind=kind, text=str(block_in.get("text", "")).strip()))

    return ParsedDoc(
        brief=brief,
        body=blocks,
        title=title,
        brand=str(payload.get("brand", "")).strip(),
    )


def _apply_title_template(template: str, h1: str) -> str:
    """Format the title template, tolerating a malformed stored template.

    Only ``{h1}`` is supported. A template that references another placeholder
    or contains stray braces would raise KeyError / IndexError mid-upload; fall
    back to the raw H1 in that case rather than aborting the post.
    """
    try:
        return template.format(h1=h1)
    except (KeyError, IndexError, ValueError):
        return h1


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _media_dir_blocks(media_dir: str | Path) -> list[Block]:
    """Build image blocks from every image file in `media_dir`, name-sorted.

    The --media-dir convenience path: the brief carries no image placement, so
    the files are appended to the body in filename order. The filename stem is a
    placeholder alt -- the operator refines it in WP admin.
    """
    d = Path(media_dir).expanduser()
    if not d.is_dir():
        raise ValueError(f"--media-dir is not a directory: {d}")
    files = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_EXTS)
    return [Block(kind="image", src=str(p), alt=p.stem) for p in files]


def _resolve_media(doc: ParsedDoc, wp: WPClient, warnings: list[str]) -> tuple[ParsedDoc, int]:
    """Upload each image block's file, filling media_id / media_url.

    Returns (resolved_doc, featured_media_id). The first image that uploads
    successfully becomes the featured image. A per-image failure is recorded as a
    warning and that block is dropped -- one bad image must never sink the whole
    post; the rest of the body still publishes as a draft.
    """
    featured = 0
    new_body: list[Block] = []
    for block in doc.body:
        if block.kind == "image" and block.src and not block.media_id:
            try:
                media = wp.upload_media(block.src, alt_text=block.alt)
            except (WPError, OSError) as e:
                warnings.append(f"Image upload failed for {Path(block.src).name}: {e}")
                continue  # drop the unrenderable block
            media_id = int(media.get("id", 0) or 0)
            block = replace(block, media_id=media_id, media_url=media.get("source_url", ""))
            if not featured and media_id:
                featured = media_id
        new_body.append(block)
    return replace(doc, body=new_body), featured


def _post_parsed_doc(doc: ParsedDoc, client_cfg: ClientConfig) -> UploadResult:
    warnings: list[str] = []
    title = _apply_title_template(client_cfg.title_template, doc.title or "Untitled")

    creds = WPCredentials.load(client_cfg.wp_credentials_path)
    wp = WPClient(creds)

    # Upload images first so the rendered body references the WP media URLs.
    doc, featured_media = _resolve_media(doc, wp, warnings)

    if not doc.body:
        # Fail loud, don't post a blank draft. SKILL.md promises "fails with a
        # clear error"; both the .docx/.md and upload-prepared paths route
        # through here, and parse_docx's own empty-body guard doesn't cover
        # upload-prepared (body: [] reaches _post_parsed_doc unchecked).
        raise ValueError(
            "Brief produced an empty body — refusing to post a blank draft. "
            "Check the brief's body content parses to at least one block before uploading."
        )

    rendered = adapters.get(client_cfg.editor)(doc)
    content, extra_meta = _split_content(client_cfg.editor, rendered)

    payload: dict[str, Any] = {
        "title": title,
        "content": content,
        "status": "draft",
    }
    if featured_media:
        payload["featured_media"] = featured_media

    if client_cfg.default_category:
        cat_id = wp.find_category_id(client_cfg.default_category)
        if cat_id:
            payload["categories"] = [cat_id]

    # Tags come only from the client's curated default_tags. The brief's
    # Keywords are deliberately NOT auto-tagged: one-off keyphrases pollute the
    # WP tag taxonomy. They still surface in the hidden TODO-META comment for
    # the writer to set as Yoast keyphrases by hand.
    tag_ids = [wp.find_or_create_tag(t) for t in client_cfg.default_tags if t]
    if tag_ids:
        payload["tags"] = tag_ids

    if extra_meta:
        payload["meta"] = extra_meta

    post = wp.create_post(payload)

    media = [{"id": b.media_id, "url": b.media_url}
             for b in doc.body if b.kind == "image" and b.media_id]
    return UploadResult(
        title=title,
        post_id=post["id"],
        post_url=post.get("link", ""),
        edit_url=f"{creds.site_base}/wp-admin/post.php?post={post['id']}&action=edit",
        brand=doc.brand,
        warnings=warnings,
        media=media,
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
