"""Parse the SEO blog brief markdown into a structured AST.

The brief is exported from Google Docs / Word as markdown (`.md` or
`.docx.md`). It may contain ONE brief or MANY briefs (one per client),
each laid out as:

    ### **<Client display name>**

    | Content Topic | <topic> |
    | :---- | :---- |
    | **Target audience** | ... |
    | **URL** | https://client.example.com/blogs/... |
    | **Keywords & Search volume** | ... |
    | **Meta Title** | ... |
    | **Meta Description** | ... |
    | **H1** | <title> |
    | **Word count** | 957 words |

    **H1: <title>**

    <body prose, blank-line separated paragraphs>

    **H2: 1\\. <sub-heading>**

    <more prose>

    - bullet list items
    - ...

Public API:
    list_briefs(md_path)           -> [BriefSummary, ...]
    parse(md_path, brand=None)     -> ParsedDoc
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Brief:
    page_url: str = ""
    h1: str = ""
    meta_title: str = ""
    meta_description: str = ""
    word_count: str = ""
    keywords: list[str] = field(default_factory=list)
    target_audience: str = ""


@dataclass
class Block:
    """One body element. kind is heading / paragraph / list / table."""
    kind: str  # 'h1' | 'h2' | 'h3' | 'h4' | 'paragraph' | 'list' | 'table'
    text: str = ""
    items: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)  # table: row-major cell HTML


@dataclass
class ParsedDoc:
    brief: Brief
    body: list[Block]
    title: str
    brand: str = ""


@dataclass
class BriefSummary:
    """Lightweight pre-scan result so the agent can pick which brief to upload."""
    brand: str
    page_url: str
    h1: str
    word_count: str


class ParseError(Exception):
    """Raised on human-facing parse failures."""


# Section header = H3 brand line. Bold wrapping is OPTIONAL since writers
# drop the ** inconsistently. The `_section_has_table()` guard below
# filters non-brand H3s (a real client section is always followed by a
# pipe table), so relaxing bold here doesn't admit false positives.
# Matches:
#   ### **AcmeCatering**
#   ### AcmeCatering
#   ### **Acme Catering**
# Skips link-only H3s like `### [**https://...**](https://...)` because
# `[` is excluded from the captured group.
# `#` is excluded from the captured name so a brand header preceded by a stray
# empty `### ` line can't pull the leftover hashes into the name (the bug that
# produced a brand literally called `### BrandName (XX)`).
_CLIENT_HEADER = re.compile(
    r"^###\s+(?:\*\*\s*([^\[\]\n*#]+?)\s*\*\*|([^\[\]\n*#][^\[\]\n*#]*?))\s*$",
    re.MULTILINE,
)


# Body headings sometimes leak into the H3 stream (writer put `**H1: ...**`
# inside a Heading3 in the source doc). Filter those so we keep only real
# client section boundaries. Accepts the full-width colon (U+FF1A) Chinese
# briefs use and the trailing-period form ("H3.") some writers type.
_BODY_HEADING_NAME = re.compile(r"^\s*H[1-4]\s*[:：.]", re.IGNORECASE)


def _section_has_table(body: str) -> bool:
    """A real client section starts with a markdown pipe table."""
    for line in body.split("\n"):
        s = line.strip()
        if not s:
            continue
        return s.startswith("|")
    return False


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Return [(brand_name, section_body), ...] in document order.

    Only sections whose name doesn't look like a body heading AND whose
    body starts with a pipe table count. This filters out cases where
    the writer accidentally rendered `**H2: ...**` inside a Heading3.
    """
    matches = list(_CLIENT_HEADER.finditer(text))
    if not matches:
        return []
    sections: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        # group 1 = bold-wrapped name, group 2 = plain name
        name = (m.group(1) or m.group(2) or "").strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        if _BODY_HEADING_NAME.match(name):
            continue
        if not _section_has_table(body):
            continue
        sections.append((name, body))
    return sections


_TABLE_ROW = re.compile(r"^\s*\|(.+?)\|\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|[\s:|\-]+\|\s*$")

_FIELD_ALIASES: dict[str, str] = {
    "url": "page_url",
    "page url": "page_url",
    "target url": "page_url",
    "h1": "h1",
    "meta title": "meta_title",
    "meta description": "meta_description",
    "word count": "word_count",
    "keywords": "keywords",
    "keywords & search volume": "keywords",
    "keyword": "keywords",
    "target audience": "target_audience",
    "audience": "target_audience",
}


# Markdown backslash-escape: a backslash before any ASCII punctuation renders
# as the literal character (the CommonMark rule). Google Docs / Word markdown
# export over-escapes punctuation -- "F\&B", "1\.", "co\-op", "50\%" -- so we
# strip the backslash to keep titles and body prose readable.
_MD_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")


def _unescape_md(s: str) -> str:
    """Drop markdown escape backslashes: ``\\X`` -> ``X`` for ASCII punctuation."""
    return _MD_ESCAPE.sub(r"\1", s)


def _strip_inline_md(text: str) -> str:
    """Drop markdown bold/escape noise from a cell value.

    Strips ALL ``**...**`` bold runs, not just a single outer pair, so a cell
    like ``**a** and **b**`` becomes ``a and b`` instead of the corrupted
    ``a** and **b``. ``***x***`` collapses cleanly too.
    """
    s = _BOLD_RE.sub(r"\1", text.strip())
    s = _ITALIC_RE.sub(r"\1", s)  # peel any remaining *italic* (e.g. from ***bold-italic***)
    s = _unescape_md(s)
    return s.strip()


# A leading label some writers leave inside the keyword cell value itself
# ("Blog Keywords: ...", "Keywords: ..."). Stripped so it doesn't become part
# of the first keyword.
_KEYWORD_LABEL = re.compile(r"^\s*(?:blog\s+)?keywords?\b[^:：]*[:：]\s*", re.IGNORECASE)


def clean_keywords(value: str) -> list[str]:
    """Parse a keyword cell into a clean list, shared by both intake paths.

    Handles the real Google-Docs shapes: a leading ``Blog Keywords:`` label,
    search-volume integers sprinkled between phrases (``... hong kong 70 ...``),
    and comma / semicolon / newline separation. Whitespace is deliberately NOT
    treated as a separator -- CJK cells are space-separated and phrases contain
    spaces, so splitting on it would shatter real phrases into fragments.
    """
    value = _KEYWORD_LABEL.sub("", value)
    out: list[str] = []
    for part in re.split(r"[,;\n]", value):
        part = re.sub(r"\b\d+\b", " ", part)   # drop bare search-volume integers
        part = " ".join(part.split())
        if part:
            out.append(part)
    return out


def _parse_table(lines: list[str]) -> tuple[Brief, int]:
    """Read pipe-delimited rows from `lines` until a non-table line.

    Returns (Brief populated from rows, index of first line AFTER the table).
    """
    brief = Brief()
    i = 0
    saw_separator = False

    while i < len(lines):
        raw = lines[i]
        m = _TABLE_ROW.match(raw)
        if not m:
            if raw.strip() == "":
                i += 1
                continue
            break

        if _TABLE_SEPARATOR.match(raw):
            saw_separator = True
            i += 1
            continue

        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) < 2:
            i += 1
            continue

        key_raw = _strip_inline_md(cells[0]).lower()
        value_raw = "|".join(cells[1:]).strip()
        value = _strip_inline_md(value_raw)

        if key_raw == "content topic" and not brief.h1:
            i += 1
            continue

        target = _FIELD_ALIASES.get(key_raw)
        if target == "keywords":
            brief.keywords = clean_keywords(value)
        elif target:
            setattr(brief, target, value)
        i += 1

    if not saw_separator and i == 0:
        return brief, 0
    return brief, i


# The href allows one level of balanced parentheses so URLs that legitimately
# contain them (e.g. a Wikipedia or tracking link ending in `(margin)`) are not
# truncated at the first `)`.
_LINK_RE = re.compile(r"\[([^\]]+)\]\(((?:[^()]|\([^()]*\))*)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"\*([^*]+)\*")


def _convert_inline(text: str) -> str:
    """Turn markdown links + bold into inline HTML, then drop MD escape backslashes.

    Unescaping runs LAST so escaped structural characters (``\\[``, ``\\*``)
    cannot masquerade as link/bold syntax during conversion.
    """
    def link_sub(m: re.Match) -> str:
        label = _BOLD_RE.sub(r"<strong>\1</strong>", m.group(1).strip())
        href = m.group(2).strip()
        return f'<a href="{href}">{label}</a>'

    s = _LINK_RE.sub(link_sub, text)
    s = _BOLD_RE.sub(r"<strong>\1</strong>", s)
    s = _unescape_md(s)
    return s.strip()


# A body heading line. Real Google-Docs exports vary the shape:
#   **H1: Title**        canonical (bold, ASCII colon)
#   **H1： 標題**         Chinese full-width colon (U+FF1A)
#   **H3. 1. Sub**       French/numbered, period instead of colon
#   #### **H1 : Title**  heading level leaked in as markdown ATX hashes
#   H2: Title            bold wrapper dropped by the writer
# The leading `#{0,6}` + optional `**` and the `[:：.]` separator cover all of
# them; the separator is the first one after the level, so an inner colon in
# the heading text (e.g. "第一招：選對") stays in the captured group.
_HEADING_LINE = re.compile(
    r"^\s*#{0,6}\s*\*{0,2}\s*(H[1-4])\s*[:：.]\s*(.+?)\s*\*{0,2}\s*$",
    re.IGNORECASE,
)
_LIST_ITEM = re.compile(r"^\s*[-*+]\s+(.+?)\s*$")


def _parse_body(text: str) -> tuple[str, list[Block]]:
    """Walk `text` line by line. Returns (h1_title, list_of_blocks)."""
    title = ""
    blocks: list[Block] = []
    buffer: list[str] = []
    list_items: list[str] = []

    def flush_paragraph() -> None:
        if not buffer:
            return
        merged = " ".join(line.strip() for line in buffer if line.strip())
        buffer.clear()
        if not merged:
            return
        blocks.append(Block(kind="paragraph", text=_convert_inline(merged)))

    def flush_list() -> None:
        if not list_items:
            return
        blocks.append(Block(
            kind="list",
            items=[_convert_inline(i) for i in list_items],
        ))
        list_items.clear()

    raw_lines = text.split("\n")
    for raw in raw_lines:
        line = raw.rstrip()

        if line.strip() == "":
            flush_paragraph()
            flush_list()
            continue

        heading = _HEADING_LINE.match(line)
        if heading:
            flush_paragraph()
            flush_list()
            kind = heading.group(1).lower()
            text_inside = _convert_inline(heading.group(2).strip())
            if kind == "h1":
                if not title:
                    title = re.sub(r"<[^>]+>", "", text_inside).strip()
                continue
            blocks.append(Block(kind=kind, text=text_inside))
            continue

        list_item = _LIST_ITEM.match(line)
        if list_item:
            flush_paragraph()
            list_items.append(list_item.group(1).strip())
            continue

        if list_items:
            flush_list()
        buffer.append(line)

    flush_paragraph()
    flush_list()
    return title, blocks


def _read(md_path: str | Path) -> str:
    p = Path(md_path).expanduser().resolve()
    if not p.exists():
        raise ParseError(f"Markdown brief not found: {p}")
    return p.read_text(encoding="utf-8")


def list_briefs(md_path: str | Path) -> list[BriefSummary]:
    """Pre-scan a markdown file to see which client briefs it contains."""
    text = _read(md_path)
    sections = _split_sections(text)
    if not sections:
        return []
    results: list[BriefSummary] = []
    for brand, body in sections:
        brief, _ = _parse_table(body.split("\n"))
        results.append(BriefSummary(
            brand=brand,
            page_url=brief.page_url,
            h1=brief.h1,
            word_count=brief.word_count,
        ))
    return results


def parse(md_path: str | Path, brand: str | None = None) -> ParsedDoc:
    """Extract one brief from `md_path` and return a populated ParsedDoc.

    If the file contains multiple briefs, pass `brand` (matched
    case-insensitively against the `### **<brand>**` section headers).
    """
    text = _read(md_path)
    sections = _split_sections(text)

    if not sections:
        return _parse_single_section(text, brand="")

    if len(sections) == 1 and brand is None:
        return _parse_single_section(sections[0][1], brand=sections[0][0])

    if brand is None:
        names = [s[0] for s in sections]
        raise ParseError(
            f"Found {len(sections)} client briefs in {md_path}: {names}. "
            f"Pass --brand to pick one."
        )

    target = brand.strip().lower()
    for name, body in sections:
        if name.strip().lower() == target:
            return _parse_single_section(body, brand=name)

    names = [s[0] for s in sections]
    raise ParseError(
        f"Brand '{brand}' not found in {md_path}. "
        f"Available: {names}"
    )


def _parse_single_section(text: str, *, brand: str) -> ParsedDoc:
    lines = text.split("\n")
    brief, table_end = _parse_table(lines)
    body_text = "\n".join(lines[table_end:])
    title_from_body, blocks = _parse_body(body_text)
    title = brief.h1 or title_from_body or brand or "Untitled"
    return ParsedDoc(brief=brief, body=blocks, title=title, brand=brand)


# ---------- inspection (debug aid for alien brief formats) -----------------


def inspect(md_path: str | Path) -> dict:
    """Diagnostic dump for the agent when strict parsing fails.

    Returns a map of every brand header, pipe table, body heading, paragraph
    count, and list count found in the file. The agent uses this to
    understand the brief's structure before deciding whether to normalize
    into parser-schema markdown or emit a `upload-prepared` JSON payload.
    """
    text = _read(md_path)

    section_headers = [(m.group(1) or m.group(2) or "").strip() for m in _CLIENT_HEADER.finditer(text)]

    tables: list[dict] = []
    current: list[str] = []
    for line in text.split("\n"):
        if _TABLE_ROW.match(line):
            current.append(line)
            continue
        if current:
            _record_table(current, tables)
            current = []
    if current:
        _record_table(current, tables)

    headings: list[dict] = []
    paragraph_count = 0
    list_count = 0
    in_paragraph = False
    in_list = False
    for line in text.split("\n"):
        if not line.strip():
            if in_paragraph:
                paragraph_count += 1
                in_paragraph = False
            if in_list:
                list_count += 1
                in_list = False
            continue
        match = _HEADING_LINE.match(line)
        if match:
            if in_paragraph:
                paragraph_count += 1
                in_paragraph = False
            if in_list:
                list_count += 1
                in_list = False
            headings.append({"level": match.group(1).lower(), "text": match.group(2).strip()})
            continue
        if _LIST_ITEM.match(line):
            if in_paragraph:
                paragraph_count += 1
                in_paragraph = False
            in_list = True
            continue
        if _TABLE_ROW.match(line):
            if in_paragraph:
                paragraph_count += 1
                in_paragraph = False
            if in_list:
                list_count += 1
                in_list = False
            continue
        in_paragraph = True
    if in_paragraph:
        paragraph_count += 1
    if in_list:
        list_count += 1

    return {
        "section_headers": section_headers,
        "tables": tables,
        "headings": headings,
        "paragraph_count": paragraph_count,
        "list_count": list_count,
    }


def _record_table(rows: list[str], out: list[dict]) -> None:
    data_rows = [r for r in rows if not _TABLE_SEPARATOR.match(r)]
    if not data_rows:
        return
    sample: list[dict] = []
    for raw in data_rows[:8]:
        m = _TABLE_ROW.match(raw)
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if not cells:
            continue
        key = _strip_inline_md(cells[0])
        value = _strip_inline_md("|".join(cells[1:])) if len(cells) > 1 else ""
        sample.append({"key": key[:80], "value": value[:120]})
    out.append({"row_count": len(data_rows), "sample_rows": sample})
