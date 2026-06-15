"""Pure-stdlib reader for .docx (WordprocessingML) brief files.

The content team exports SEO briefs from Google Docs / Word with the
article body wrapped inside a table cell. The markdown export flattens
that cell into a single physical line -- destroying every heading and
paragraph boundary -- whereas the .docx keeps each one as a separate
``<w:p>`` even inside a ``<w:tc>``. This module exposes the low-level
primitives ``parse_docx`` builds on: an ordered walk of the body's
block children (paragraphs + tables), run-text joining (Word splits a
sentence into several ``<w:r>`` runs at every bold/highlight boundary),
paragraph style + bold detection, hyperlink resolution to real URLs,
and runs -> inline HTML.

Inline HTML matches ``parse_md``'s contract: ``Para.html`` returns raw
(un-escaped) text with ``<a>`` / ``<strong>`` tags inlined -- the editor
adapters do the HTML-escaping downstream, identically for both intake
paths.

Pure stdlib: ``zipfile`` + ``xml.etree.ElementTree``. No pip, matching
the skill's philosophy.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

# WordprocessingML main namespace + the relationship namespace used on
# ``r:id`` attributes (hyperlinks point into word/_rels/document.xml.rels).
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _w(tag: str) -> str:
    return f"{{{_W}}}{tag}"


def _r(tag: str) -> str:
    return f"{{{_R}}}{tag}"


class DocxError(Exception):
    """Raised when a file is not a readable .docx."""


def _reject_dtd(data: bytes) -> None:
    """Raise if the XML prolog declares a DOCTYPE.

    stdlib ``etree`` refuses to expand *external* entities (no XXE, no file
    exfiltration -- it raises), but it DOES expand internal entities, so a
    DOCTYPE enables a "billion laughs" expansion DoS. Briefs are untrusted
    input (see README security model) and ``defusedxml`` is unavailable
    under the no-pip rule, so forbid the DOCTYPE outright -- a real .docx
    never declares one, and with no DOCTYPE no entities can be defined.

    A byte-level prolog scan (skipping the XML declaration, processing
    instructions, and comments) is used rather than an expat handler: the
    C-accelerated ``ET.XMLParser`` does not expose its expat instance.
    """
    i, n = 0, len(data)
    while i < n:
        lt = data.find(b"<", i)
        if lt == -1:
            return
        if data[lt:lt + 2] == b"<?":          # XML declaration / processing instruction
            end = data.find(b"?>", lt)
            if end == -1:
                return
            i = end + 2
        elif data[lt:lt + 4] == b"<!--":      # comment
            end = data.find(b"-->", lt)
            if end == -1:
                return
            i = end + 3
        elif data[lt:lt + 9].upper() == b"<!DOCTYPE":
            raise DocxError("DTD/DOCTYPE not allowed in .docx XML (entity-expansion guard)")
        else:
            return                            # reached the root element, no DOCTYPE


def _safe_fromstring(data: bytes) -> ET.Element:
    """Parse XML with DOCTYPE declarations forbidden (entity-expansion guard)."""
    _reject_dtd(data)
    return ET.fromstring(data)


# ---------- run-level helpers ----------------------------------------------


def _is_bold_run(run: ET.Element) -> bool:
    """A run is bold unless ``<w:b>`` is explicitly switched off."""
    rpr = run.find(_w("rPr"))
    if rpr is None:
        return False
    b = rpr.find(_w("b"))
    if b is None:
        return False
    return b.get(_w("val")) not in ("0", "false", "none", "off")


def _run_text(run: ET.Element) -> str:
    """Concatenate the text payload of one ``<w:r>`` (text, tabs, breaks)."""
    parts: list[str] = []
    for node in run.iter():
        if node.tag == _w("t"):
            parts.append(node.text or "")
        elif node.tag == _w("tab"):
            parts.append("\t")
        elif node.tag in (_w("br"), _w("cr")):
            parts.append("\n")
    return "".join(parts)


def _run_html(run: ET.Element) -> str:
    """One run as inline HTML: bold wrapped in ``<strong>``, text raw.

    Text is left un-escaped on purpose -- this mirrors ``parse_md``'s
    ``Block.text`` shape so the editor adapters escape both paths the
    same way.
    """
    text = _run_text(run)
    if not text:
        return ""
    return f"<strong>{text}</strong>" if _is_bold_run(run) else text


# ---------- block wrappers --------------------------------------------------


class Para:
    """One ``<w:p>`` paragraph."""

    def __init__(self, element: ET.Element, rels: dict[str, str]):
        self._el = element
        self._rels = rels

    @property
    def text(self) -> str:
        """Plain text in document order, including hyperlink labels."""
        parts: list[str] = []
        for node in self._el.iter():
            if node.tag == _w("t"):
                parts.append(node.text or "")
            elif node.tag == _w("tab"):
                parts.append("\t")
            elif node.tag in (_w("br"), _w("cr")):
                parts.append("\n")
        return "".join(parts).strip()

    @property
    def html(self) -> str:
        """Inline HTML: runs -> text/``<strong>``, hyperlinks -> ``<a>``."""
        out: list[str] = []
        for child in self._el:
            if child.tag == _w("r"):
                out.append(_run_html(child))
            elif child.tag == _w("hyperlink"):
                inner = "".join(_run_html(r) for r in child.findall(_w("r")))
                rid = child.get(_r("id"))
                href = self._rels.get(rid, "") if rid else ""
                out.append(f'<a href="{href}">{inner}</a>' if href else inner)
        return "".join(out).strip()

    @property
    def style(self) -> str:
        """Paragraph style id (e.g. ``Heading3``), or ``""``."""
        ppr = self._el.find(_w("pPr"))
        if ppr is None:
            return ""
        style = ppr.find(_w("pStyle"))
        return style.get(_w("val"), "") if style is not None else ""

    @property
    def is_bold(self) -> bool:
        """True when every run carrying text is bold (a typed-heading signal)."""
        runs = self._el.findall(".//" + _w("r"))
        text_runs = [r for r in runs if _run_text(r).strip()]
        return bool(text_runs) and all(_is_bold_run(r) for r in text_runs)


class Cell:
    """One ``<w:tc>`` table cell.

    ``blocks`` preserves document order (paragraphs and nested tables
    interleaved); ``paras`` / ``tables`` are order-losing views kept for
    convenience.
    """

    def __init__(self, blocks: list["Para | Table"]):
        self.blocks = blocks

    @property
    def paras(self) -> list[Para]:
        return [b for b in self.blocks if isinstance(b, Para)]

    @property
    def tables(self) -> list["Table"]:
        return [b for b in self.blocks if isinstance(b, Table)]

    @property
    def text(self) -> str:
        return " ".join(p.text for p in self.paras if p.text).strip()


class Table:
    """One ``<w:tbl>`` as a grid of cells."""

    def __init__(self, rows: list[list[Cell]]):
        self.rows = rows

    def cells(self) -> list[Cell]:
        """All cells, row-major order."""
        return [c for row in self.rows for c in row]

    @property
    def label(self) -> str:
        """Text of the first cell -- the field label in the house template."""
        flat = self.cells()
        return flat[0].text if flat else ""


class Document:
    """A parsed .docx body: ordered block children + the relationship map."""

    def __init__(self, blocks: list[Para | Table], rels: dict[str, str]):
        self.blocks = blocks
        self.rels = rels

    @property
    def paragraphs(self) -> list[Para]:
        return [b for b in self.blocks if isinstance(b, Para)]

    @property
    def tables(self) -> list[Table]:
        return [b for b in self.blocks if isinstance(b, Table)]


# ---------- construction ----------------------------------------------------


def _build_table(tbl_el: ET.Element, rels: dict[str, str]) -> Table:
    rows: list[list[Cell]] = []
    for tr in tbl_el.findall(_w("tr")):
        row: list[Cell] = []
        for tc in tr.findall(_w("tc")):
            blocks: list[Para | Table] = []
            for child in tc:
                if child.tag == _w("p"):
                    blocks.append(Para(child, rels))
                elif child.tag == _w("tbl"):
                    blocks.append(_build_table(child, rels))
            row.append(Cell(blocks))
        rows.append(row)
    return Table(rows)


def _read_rels(zf: zipfile.ZipFile) -> dict[str, str]:
    """Map ``rId`` -> target URL from word/_rels/document.xml.rels."""
    try:
        raw = zf.read("word/_rels/document.xml.rels")
    except KeyError:
        return {}
    rels: dict[str, str] = {}
    for rel in _safe_fromstring(raw):
        rid = rel.get("Id")
        if rid:
            rels[rid] = rel.get("Target", "")
    return rels


def read(path: str | Path) -> Document:
    """Open a .docx and return its body as ordered blocks + rels map."""
    p = Path(path).expanduser()
    try:
        zf = zipfile.ZipFile(p)
    except (zipfile.BadZipFile, OSError) as e:
        raise DocxError(f"Not a readable .docx: {p} ({e})") from e

    with zf:
        try:
            doc_xml = zf.read("word/document.xml")
        except KeyError as e:
            raise DocxError(f"Missing word/document.xml in {p} (not a Word .docx?)") from e
        rels = _read_rels(zf)

    body = _safe_fromstring(doc_xml).find(_w("body"))
    if body is None:
        raise DocxError(f"No <w:body> in {p}")

    blocks: list[Para | Table] = []
    for child in body:
        if child.tag == _w("p"):
            blocks.append(Para(child, rels))
        elif child.tag == _w("tbl"):
            blocks.append(_build_table(child, rels))
    return Document(blocks, rels)
