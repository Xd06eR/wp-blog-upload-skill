"""Tests for parse_docx -- house-template .docx -> ParsedDoc.

Synthetic in-memory .docx fixtures (no real client briefs in the repo).
Run from the skill root:
    PYTHONPATH=. python3 -B -m unittest tests.test_parse_docx -v
"""

from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.tools import parse_docx
from scripts.tools.parse_md import ParseError

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _r(text: str, bold: bool = False) -> str:
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'


def _p(*runs: str) -> str:
    return f"<w:p>{''.join(runs)}</w:p>"


def _cell(*paras: str) -> str:
    return f"<w:tc>{''.join(paras)}</w:tc>"


def _row(*cells: str) -> str:
    return f"<w:tr>{''.join(cells)}</w:tr>"


def _table(*rows: str) -> str:
    return f"<w:tbl>{''.join(rows)}</w:tbl>"


def _field(label: str, value: str) -> str:
    """A label-then-value field table (IV / V / VI style)."""
    return _table(_row(_cell(_p(_r(label)))), _row(_cell(_p(_r(value)))))


def _docx(body_xml: str, rels_xml: str = "") -> str:
    document = (
        f'<?xml version="1.0"?>'
        f"<w:document {_W} {_RNS}><w:body>{body_xml}</w:body></w:document>"
    )
    rels = (
        '<?xml version="1.0"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{rels_xml}</Relationships>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", document)
        zf.writestr("word/_rels/document.xml.rels", rels)
    tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    tmp.write(buf.getvalue())
    tmp.close()
    return tmp.name


# A single-body house brief mirroring the real FPD export shape, including the
# boilerplate Heading3 sections that live OUTSIDE the body table (must NOT leak).
def _house_body(body_cell_paras: str, *, title_cell: str = "IV.title",
                meta_cell: str = "V.meta", client_url: str = "https://acme.example/") -> str:
    boilerplate = (
        '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr>' + _r("Purpose of SEO Content") + "</w:p>"
        + _p(_r("This boilerplate must never appear in the body."))
    )
    client_tbl = _table(
        _row(_cell(_p(_r("Client Name"))), _cell(_p(_r("Acme Co")))),
        _row(_cell(_p(_r("Client URL"))), _cell(_p(_r(client_url)))),
    )
    page_url_tbl = _table(
        _row(_cell(_p(_r("I. Page URL"))), _cell(_p(_r("Page Type"))), _cell(_p(_r("Word Count")))),
        _row(_cell(_p(_r(""))), _cell(_p(_r("New"))), _cell(_p(_r("1000")))),
    )
    return (
        boilerplate
        + client_tbl
        + page_url_tbl
        + _field("IV. Page title (Max. Pixel Width: 580px)", title_cell)
        + _field("V. Meta description (Max. Pixel Width: 880px)", meta_cell)
        + _table(_row(_cell(_p(_r("VI. Body content")))), _row(_cell(body_cell_paras)))
    )


class ParseDocxHouseSingleTest(unittest.TestCase):
    def setUp(self) -> None:
        self._paths: list[str] = []

    def tearDown(self) -> None:
        for p in self._paths:
            Path(p).unlink(missing_ok=True)

    def _write(self, body_xml: str, rels_xml: str = "") -> str:
        path = _docx(body_xml, rels_xml)
        self._paths.append(path)
        return path

    def test_full_width_colon_h1_becomes_title(self) -> None:
        body = _p(_r("H1： 想擁有女團同款太陽花眼睫毛", bold=True)) + _p(_r("近年韓國女團掀起熱潮。"))
        doc = parse_docx.parse(self._write(_house_body(body)))
        self.assertEqual(doc.title, "想擁有女團同款太陽花眼睫毛")
        self.assertNotIn("H1", doc.title)

    def test_headings_and_paragraphs_in_order(self) -> None:
        body = (
            _p(_r("H1: Main Title", bold=True))
            + _p(_r("Intro paragraph."))
            + _p(_r("H2: First Section", bold=True))
            + _p(_r("Section body."))
            + _p(_r("H3: Sub Section", bold=True))
        )
        doc = parse_docx.parse(self._write(_house_body(body)))
        kinds = [(b.kind, b.text) for b in doc.body]
        self.assertEqual(kinds, [
            ("paragraph", "Intro paragraph."),
            ("h2", "First Section"),
            ("paragraph", "Section body."),
            ("h3", "Sub Section"),
        ])

    def test_inner_colon_in_h3_preserved(self) -> None:
        body = _p(_r("H1: T", bold=True)) + _p(_r("H3： 第一招：選對睫毛夾", bold=True)) + _p(_r("prose"))
        doc = parse_docx.parse(self._write(_house_body(body)))
        h3 = [b.text for b in doc.body if b.kind == "h3"]
        self.assertEqual(h3, ["第一招：選對睫毛夾"])

    def test_link_in_body_preserved_with_real_url(self) -> None:
        link = '<w:hyperlink r:id="rId9">' + _r("our shop") + "</w:hyperlink>"
        body = _p(_r("H1: T", bold=True)) + _p(_r("Visit "), link, _r(" now"))
        rels = '<Relationship Id="rId9" Target="https://acme.example/p?a=1&amp;b=2"/>'
        doc = parse_docx.parse(self._write(_house_body(body), rels))
        para = [b.text for b in doc.body if b.kind == "paragraph"][0]
        self.assertEqual(para, 'Visit <a href="https://acme.example/p?a=1&b=2">our shop</a> now')

    def test_meta_and_url_extracted(self) -> None:
        body = _p(_r("H1: T", bold=True)) + _p(_r("x"))
        doc = parse_docx.parse(self._write(
            _house_body(body, title_cell="My SEO Title", meta_cell="My meta desc",
                        client_url="https://acme.example/")))
        self.assertEqual(doc.brief.meta_title, "My SEO Title")
        self.assertEqual(doc.brief.meta_description, "My meta desc")
        self.assertEqual(doc.brief.page_url, "https://acme.example/")
        self.assertEqual(doc.brief.word_count, "1000")

    def test_boilerplate_never_leaks_into_body(self) -> None:
        body = _p(_r("H1: T", bold=True)) + _p(_r("Real body."))
        doc = parse_docx.parse(self._write(_house_body(body)))
        joined = " ".join(b.text for b in doc.body)
        self.assertNotIn("boilerplate", joined)
        self.assertNotIn("Purpose of SEO Content", joined)

    def test_empty_body_cell_raises(self) -> None:
        doc_path = self._write(_house_body(_p(_r(""))))
        with self.assertRaises(ParseError):
            parse_docx.parse(doc_path)

    def test_no_h1_and_no_title_raises(self) -> None:
        # body has only an H2, and the IV. Page title cell is blank.
        body = _p(_r("H2: orphan", bold=True)) + _p(_r("text"))
        doc_path = self._write(_house_body(body, title_cell=""))
        with self.assertRaises(ParseError):
            parse_docx.parse(doc_path)

    def test_no_h1_falls_back_to_page_title(self) -> None:
        body = _p(_r("H2: only", bold=True)) + _p(_r("text"))
        doc = parse_docx.parse(self._write(_house_body(body, title_cell="Fallback Title")))
        self.assertEqual(doc.title, "Fallback Title")

    def test_list_briefs_returns_one_summary(self) -> None:
        body = _p(_r("H1: The Title", bold=True)) + _p(_r("x"))
        briefs = parse_docx.list_briefs(self._write(_house_body(body)))
        self.assertEqual(len(briefs), 1)
        self.assertEqual(briefs[0].h1, "The Title")
        self.assertEqual(briefs[0].word_count, "1000")


if __name__ == "__main__":
    unittest.main()