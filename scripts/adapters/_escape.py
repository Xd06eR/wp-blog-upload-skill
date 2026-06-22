"""Shared HTML-escaping helper for the editor adapters.

Body text reaches the adapters already carrying intentional inline HTML
(``<a href>``, ``<strong>`` from the parsers). The naive approach -- escape
the whole string only when it has NO tag -- is all-or-nothing: a block that
mixes a link with ordinary prose ships every other ``&`` / ``<`` / ``>`` raw,
producing invalid HTML (``F&B`` and ``?a=1&b=2`` are the common casualties).

``escape_inline`` instead escapes only the spans BETWEEN the recognized inline
tags, leaving the tags themselves intact, so both the markup and the literal
punctuation come out correct.
"""

from __future__ import annotations

import re

# Recognized inline tags we pass through untouched: <a ...>, </a>, <strong>,
# </strong>, <em>, </em>, <br>. Anything else is treated as literal text.
_INLINE_TAG = re.compile(
    r"</?(?:a|strong|em|b|i|br)(?:\s[^<>]*)?>",
    re.IGNORECASE,
)

# A bare `&` that does NOT already start an entity (`&amp;`, `&#39;`, ...).
# Used for both text spans and href attributes so an already-encoded entity is
# never double-escaped (`&amp;` must not become `&amp;amp;`).
_BARE_AMP = re.compile(r"&(?!#?\w+;)")

# href attribute inside an <a> tag (parsers emit double-quoted hrefs). Used to
# neutralize dangerous URL schemes — see `_sanitize_a_href`.
_HREF_ATTR = re.compile(r'\s+href\s*=\s*"([^"]*)"', re.IGNORECASE)
# A leading `scheme:` on a URL. A URL is treated as unsafe if it carries a
# scheme NOT in `_SAFE_SCHEMES`; scheme-less URLs (relative paths, `#anchor`)
# have no scheme and pass through.
_SCHEME = re.compile(r"^([a-z][a-z0-9+.\-]*):", re.IGNORECASE)
_SAFE_SCHEMES = {"http", "https", "mailto", "tel"}


def _escape_text(text: str) -> str:
    """Escape a literal text span: bare `&` then the angle brackets."""
    return _BARE_AMP.sub("&amp;", text).replace("<", "&lt;").replace(">", "&gt;")


def _escape_attr(text: str) -> str:
    """Escape a value for a double-quoted HTML attribute (image alt / src).

    Text-span rules plus the double-quote, since the value sits inside `"..."`.
    Bare `&` only, so an already-encoded entity is never doubled.
    """
    return _escape_text(text).replace('"', "&quot;")


def _sanitize_a_href(tag: str) -> str:
    """Strip an unsafe href (``javascript:``, ``data:``, ``vbscript:``, ...) from an ``<a>`` tag.

    WP bypasses ``wp_kses`` for Editor/Admin (``unfiltered_html``), so the skill
    must sanitize brief-sourced URLs itself rather than rely on WP. Safe schemes
    (http/https/mailto/tel) and scheme-less URLs (relative paths, anchors) pass
    through unchanged; only the ``href`` attribute is dropped on an unsafe URL —
    the ``<a>`` tag and its link text always survive.
    """
    m = _HREF_ATTR.search(tag)
    if not m:
        return tag
    scheme = _SCHEME.match(m.group(1).strip())
    if scheme is None or scheme.group(1).lower() in _SAFE_SCHEMES:
        return tag
    return tag[:m.start()] + tag[m.end():]  # drop the href attr, keep the tag


def escape_inline(text: str) -> str:
    """Escape literal text spans but leave recognized inline HTML tags intact.

    Unsafe ``<a href>`` schemes are stripped (see ``_sanitize_a_href``).
    """
    out: list[str] = []
    last = 0
    for m in _INLINE_TAG.finditer(text):
        out.append(_escape_text(text[last:m.start()]))
        tag = m.group(0)
        if tag.lower().startswith("<a"):  # opening anchor — sanitize its href
            tag = _sanitize_a_href(tag)
        out.append(_BARE_AMP.sub("&amp;", tag))  # fix bare & in href, keep tag
        last = m.end()
    out.append(_escape_text(text[last:]))
    return "".join(out)


def comment_safe(text: str) -> str:
    """Neutralize a field interpolated into an HTML comment.

    A meta title / description containing ``-->`` (or a Word em-dash artifact
    that normalizes to ``--`` before a ``>``) would otherwise close the hidden
    ``<!-- TODO META ... -->`` block early and leak the remaining fields into
    the visible draft body. Inserting an en-dash between the dashes and the
    angle bracket keeps the note hidden while staying readable.
    """
    return text.replace("-->", "--–>") if text else text


def build_todo_meta(brief, *, extra_lines: tuple[str, ...] = ()) -> str:
    """The hidden ``<!-- TODO META FOR HUMAN -->`` note shared by all adapters.

    Reminds the writer to fill Yoast / RankMath / AIOSEO by hand (those plugins
    have no REST API). Every interpolated field is run through ``comment_safe``
    so a stray ``-->`` cannot break out of the comment.
    """
    keywords = ", ".join(brief.keywords) if brief.keywords else "(none)"
    lines = [
        "<!-- TODO META FOR HUMAN:",
        "  - Fill SEO title + meta description in Yoast / RankMath / AIOSEO (no REST API)",
        f"  - Meta title (suggested): {comment_safe(brief.meta_title) or '(none)'}",
        f"  - Meta description (suggested): {comment_safe(brief.meta_description) or '(none)'}",
        f"  - Target URL: {comment_safe(brief.page_url) or '(not specified)'}",
        f"  - Keywords: {comment_safe(keywords)}",
        *(f"  {line}" for line in extra_lines),
        "-->",
    ]
    return "\n".join(lines)
