"""Parse a .docx SEO brief into the same ParsedDoc the markdown path uses.

The content team wraps the article body in a Word table cell. Markdown
export flattens that cell to one line (structure lost); the .docx keeps
every heading + paragraph as a separate ``<w:p>`` inside the ``<w:tc>``.
This module reads the .docx natively (via ``docx_reader``) and emits the
exact ``Brief`` / ``Block`` / ``ParsedDoc`` shapes ``parse_md`` produces,
so the renderer + uploader downstream are unchanged.

FPD "house template" layout (each field is its own table, labelled by its
first cell):

    | Date | ... |                         <- generic header  (skipped)
    | Client Name | ... | Client URL | ... | <- page_url source
    | I. Page URL | Page Type | Word Count |  <- word_count
    | II. Keyword(s) for the page |           <- keywords (filled in B2)
    | III. Special Requirement |              <- skipped
    | IV. Page title (...) |                  <- meta_title
    | V. Meta description (...) |             <- meta_description
    | VI. Body content |                      <- the body cell

Public API mirrors ``parse_md``:
    list_briefs(path) -> [BriefSummary, ...]
    parse(path, brand=None) -> ParsedDoc

This commit (A2) handles the SINGLE-body house brief. Multi-body files
(one .docx, several VI. Body content tables) and the paragraph-stream
multi-brief layout are added next.

Pure stdlib via ``docx_reader``. No pip.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import docx_reader
from .parse_md import Block, Brief, BriefSummary, ParseError, ParsedDoc, _convert_inline

# Body headings are typed text ("H1： title" / "H2: title"), NOT Word heading
# styles. Full-width colon (U+FF1A) is what the Chinese briefs use; ASCII for
# English. The first colon after the level ends the marker, so any inner colon
# in the heading text (e.g. "第一招：選對睫毛夾") is preserved in group 2.
_HEADING_RE = re.compile(r"^\s*#{0,6}\s*H([1-4])\s*[:：.]\s*(.+?)\s*$", re.IGNORECASE)

# A field table is identified by its first-cell label. Strip the leading Roman
# numeral ("iv. ") before matching so the "(Max. Pixel Width …)" suffix is all
# that follows the canonical token.
_ROMAN_PREFIX = re.compile(r"^[ivx]+\.\s*", re.IGNORECASE)


def _classify(label: str) -> str:
    s = _ROMAN_PREFIX.sub("", label.strip().lower())
    if s.startswith("page url"):
        return "page_url_grid"
    if s.startswith("keyword"):
        return "keywords"
    if s.startswith("page title"):
        return "meta_title"
    if s.startswith("meta description"):
        return "meta_description"
    if s.startswith("body content"):
        return "body"
    return ""


def _body_tables(doc: docx_reader.Document) -> list[docx_reader.Table]:
    return [t for t in doc.tables if _classify(t.label) == "body"]


def _brand_markers(doc: docx_reader.Document) -> list[tuple[int, str]]:
    """Paragraph-stream brand headers: non-empty ``Heading3`` blocks.

    Returns (block_index, brand_name) for each. Empty Heading3 paragraphs
    (placeholder brands like KitchenPark AR / KitchenBASE JP in the real
    briefs) are skipped — they carry no body.
    """
    out: list[tuple[int, str]] = []
    for i, block in enumerate(doc.blocks):
        if isinstance(block, docx_reader.Para) and block.style == "Heading3" and block.text.strip():
            out.append((i, block.text.strip()))
    return out


def _value_cell_text(table: docx_reader.Table) -> str:
    """Value of a label-then-value field table (II/IV/V): last row, last cell."""
    if not table.rows:
        return ""
    return table.rows[-1][-1].text


def _find_kv(doc: docx_reader.Document, *keys: str) -> str:
    """Scan 2-column key|value grid tables (Date / Client Name) for a key."""
    wanted = {k.lower() for k in keys}
    for table in doc.tables:
        for row in table.rows:
            if len(row) >= 2 and row[0].text.strip().lower() in wanted:
                val = row[1].text.strip()
                if val:
                    return val
    return ""


def _extract_brief(doc: docx_reader.Document) -> Brief:
    brief = Brief()
    for table in doc.tables:
        kind = _classify(table.label)
        if kind == "meta_title":
            brief.meta_title = _value_cell_text(table)
        elif kind == "meta_description":
            brief.meta_description = _value_cell_text(table)
        elif kind == "page_url_grid":
            # rows[0] = headers (Page URL | Page Type | Word Count),
            # rows[1] = data. The URL cell often holds the topic or is blank,
            # so only trust it when it looks like a URL; word count is reliable.
            if len(table.rows) >= 2:
                data = table.rows[-1]
                if data and data[0].text.startswith("http"):
                    brief.page_url = data[0].text.strip()
                if len(data) >= 2:
                    brief.word_count = data[-1].text.strip()
    if not brief.page_url:
        brief.page_url = _find_kv(doc, "client url", "client")
    # keywords are populated by the shared keyword cleaner (B2).
    return brief


def _table_block(table: docx_reader.Table) -> Block:
    """A nested in-body table -> a ``table`` Block (row-major cell HTML).

    The body cell sometimes embeds a real Word table (schedule / comparison
    grid). ParsedDoc carries it as ``kind='table'`` with ``rows`` so the
    adapters can emit valid ``<table>`` markup instead of a mangled
    ``<p><table></p>``.
    """
    rows = [[cell.text and (cell.paras[0].html if cell.paras else cell.text) or ""
             for cell in row] for row in table.rows]
    return Block(kind="table", rows=rows)


def _parse_body_cell(cell: docx_reader.Cell) -> tuple[str, list[Block]]:
    """Turn the body cell's ordered blocks into (title, blocks).

    H1 becomes the post title (not a block, matching parse_md). H2-H4 are
    heading blocks; nested tables become ``table`` blocks in place; every
    other paragraph is a paragraph block with inline links/bold preserved.
    """
    title = ""
    blocks: list[Block] = []
    for item in cell.blocks:
        if isinstance(item, docx_reader.Table):
            blocks.append(_table_block(item))
            continue
        text = item.text
        if not text:
            continue
        m = _HEADING_RE.match(text)
        if m:
            level = int(m.group(1))
            heading_text = m.group(2).strip()
            if level == 1:
                if not title:
                    title = heading_text
                continue
            blocks.append(Block(kind=f"h{level}", text=_convert_inline(heading_text)))
            continue
        blocks.append(Block(kind="paragraph", text=item.html))
    return title, blocks


def _parse_house_single(doc: docx_reader.Document, body_table: docx_reader.Table,
                        *, path: Path) -> ParsedDoc:
    body_cell = body_table.rows[-1][-1]
    title, blocks = _parse_body_cell(body_cell)
    brief = _extract_brief(doc)

    if not blocks:
        raise ParseError(
            f"House-template .docx {path} has an empty 'VI. Body content' cell — "
            f"nothing to upload."
        )
    title = title or brief.meta_title
    if not title:
        raise ParseError(
            f"House-template .docx {path} has no H1 heading and no page title — "
            f"cannot derive a post title."
        )
    brief.h1 = title
    return ParsedDoc(brief=brief, body=blocks, title=title, brand="")


# ---------- multi-body (one .docx, several VI. Body content tables) ---------


def _brief_from_field_tables(tables: list[docx_reader.Table]) -> Brief:
    """Build a Brief from a flat list of field tables (no doc-wide scan)."""
    brief = Brief()
    for table in tables:
        kind = _classify(table.label)
        if kind == "meta_title":
            brief.meta_title = _value_cell_text(table)
        elif kind == "meta_description":
            brief.meta_description = _value_cell_text(table)
        elif kind == "page_url_grid" and len(table.rows) >= 2:
            data = table.rows[-1]
            if data and data[0].text.startswith("http"):
                brief.page_url = data[0].text.strip()
            if len(data) >= 2:
                brief.word_count = data[-1].text.strip()
    return brief


def _split_bodies(doc: docx_reader.Document) -> list[tuple[Brief, docx_reader.Table]]:
    """Group tables into (brief, body_table) per VI. Body content cell.

    Each body's metadata is the field tables seen since the previous body.
    A translation block that ships only IV/V (no page_url/keywords of its
    own) inherits the most recent page_url + word_count from its sibling.
    """
    out: list[tuple[Brief, docx_reader.Table]] = []
    pending: list[docx_reader.Table] = []
    last_url, last_wc = "", ""
    for table in doc.tables:
        kind = _classify(table.label)
        if kind == "body":
            brief = _brief_from_field_tables(pending)
            if brief.page_url:
                last_url = brief.page_url
            else:
                brief.page_url = last_url
            if brief.word_count:
                last_wc = brief.word_count
            else:
                brief.word_count = last_wc
            out.append((brief, table))
            pending = []
        elif kind:
            pending.append(table)
    return out


def _finalize(brief: Brief, body_table: docx_reader.Table, *, brand: str,
              path: Path, label: str) -> ParsedDoc:
    title, blocks = _parse_body_cell(body_table.rows[-1][-1])
    if not blocks:
        raise ParseError(f"{path}: body section '{label}' is empty — nothing to upload.")
    title = title or brief.meta_title
    if not title:
        raise ParseError(f"{path}: body section '{label}' has no H1 and no page title.")
    brief.h1 = title
    return ParsedDoc(brief=brief, body=blocks, title=title, brand=brand)


def _body_label(brief: Brief, index: int) -> str:
    """A stable selector label for a body in a multi-body file."""
    return brief.meta_title.strip() or f"body {index + 1}"


# ---------- paragraph-stream multi-brief (10-blog: Heading3 per brand) ------


def _parse_brand_stream(doc: docx_reader.Document, start: int, end: int,
                        *, brand: str, path: Path) -> ParsedDoc:
    """Parse one brand's body from the paragraph slice (start, end)."""
    title = ""
    blocks: list[Block] = []
    for block in doc.blocks[start:end]:
        if not isinstance(block, docx_reader.Para):
            continue
        text = block.text
        if not text:
            continue
        m = _HEADING_RE.match(text)
        if m:
            level = int(m.group(1))
            htext = m.group(2).strip()
            if level == 1:
                if not title:
                    title = htext
                continue
            blocks.append(Block(kind=f"h{level}", text=_convert_inline(htext)))
            continue
        blocks.append(Block(kind="paragraph", text=block.html))
    if not title or not blocks:
        raise ParseError(f"{path}: brand '{brand}' has no H1 or no body.")
    return ParsedDoc(brief=Brief(h1=title), body=blocks, title=title, brand=brand)


# ---------- public dispatch -------------------------------------------------


def parse(path: str | Path, brand: str | None = None) -> ParsedDoc:
    """Parse one brief from a .docx into a ParsedDoc.

    Three layouts, auto-detected:
      - single VI. Body content table  -> the house single brief
      - several VI. Body content tables -> multi-body; pass `brand` to pick
      - no body table, Heading3 brands  -> paragraph-stream multi-brief
    """
    p = Path(path).expanduser()
    doc = docx_reader.read(p)
    bodies = _body_tables(doc)

    if len(bodies) == 1:
        return _parse_house_single(doc, bodies[0], path=p)

    if len(bodies) > 1:
        sections = _split_bodies(doc)
        labels = [_body_label(b, i) for i, (b, _) in enumerate(sections)]
        if brand is None:
            raise ParseError(
                f"Found {len(sections)} body sections in {p}: {labels}. Pass --brand to pick one."
            )
        target = brand.strip().lower()
        for i, (b, tbl) in enumerate(sections):
            if labels[i].lower() == target:
                return _finalize(b, tbl, brand=labels[i], path=p, label=labels[i])
        raise ParseError(f"Body section '{brand}' not found in {p}. Available: {labels}")

    markers = _brand_markers(doc)
    if markers:
        names = [m[1] for m in markers]
        if brand is None:
            raise ParseError(
                f"Found {len(markers)} client briefs in {p}: {names}. Pass --brand to pick one."
            )
        target = brand.strip().lower()
        for idx, (block_i, name) in enumerate(markers):
            if name.lower() == target:
                end = markers[idx + 1][0] if idx + 1 < len(markers) else len(doc.blocks)
                return _parse_brand_stream(doc, block_i + 1, end, brand=name, path=p)
        raise ParseError(f"Brand '{brand}' not found in {p}. Available: {names}")

    raise ParseError(f"No recognizable brief sections in {p}.")


def list_briefs(path: str | Path) -> list[BriefSummary]:
    """Pre-scan a .docx for its brief sections (all layouts)."""
    p = Path(path).expanduser()
    doc = docx_reader.read(p)
    bodies = _body_tables(doc)

    if len(bodies) == 1:
        brief = _extract_brief(doc)
        title, _ = _parse_body_cell(bodies[0].rows[-1][-1])
        return [BriefSummary(
            brand=_find_kv(doc, "client name", "client") or "",
            page_url=brief.page_url,
            h1=title or brief.meta_title,
            word_count=brief.word_count,
        )]

    if len(bodies) > 1:
        out: list[BriefSummary] = []
        for i, (brief, tbl) in enumerate(_split_bodies(doc)):
            title, _ = _parse_body_cell(tbl.rows[-1][-1])
            out.append(BriefSummary(
                brand=_body_label(brief, i),
                page_url=brief.page_url,
                h1=title or brief.meta_title,
                word_count=brief.word_count,
            ))
        return out

    return [BriefSummary(brand=name, page_url="", h1="", word_count="")
            for _, name in _brand_markers(doc)]