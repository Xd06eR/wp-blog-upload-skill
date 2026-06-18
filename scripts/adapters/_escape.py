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
