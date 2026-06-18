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


def _escape_text(text: str) -> str:
    """Escape a literal text span: bare `&` then the angle brackets."""
    return _BARE_AMP.sub("&amp;", text).replace("<", "&lt;").replace(">", "&gt;")


def _escape_attr(text: str) -> str:
    """Escape a value for a double-quoted HTML attribute (image alt / src).

    Text-span rules plus the double-quote, since the value sits inside `"..."`.
    Bare `&` only, so an already-encoded entity is never doubled.
    """
    return _escape_text(text).replace('"', "&quot;")


def escape_inline(text: str) -> str:
    """Escape literal text spans but leave recognized inline HTML tags intact."""
    out: list[str] = []
    last = 0
    for m in _INLINE_TAG.finditer(text):
        out.append(_escape_text(text[last:m.start()]))
        out.append(_BARE_AMP.sub("&amp;", m.group(0)))  # fix bare & in href, keep tag
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
