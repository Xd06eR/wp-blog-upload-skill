"""Tests for docx_reader -- pure-stdlib WordprocessingML primitives.

Fixtures are synthetic .docx files built in-memory (zipfile) so no real
client brief ever lands in the repo. Run from the skill root:
    PYTHONPATH=. python3 -B -m unittest tests.test_docx_reader -v
"""

from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.tools import docx_reader

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _docx(document_body_xml: str, rels_xml: str = "") -> str:
    """Write a minimal valid .docx to a temp file, return its path."""
    document = (
        f'<?xml version="1.0"?>'
        f"<w:document {_W} {_RNS}><w:body>{document_body_xml}</w:body></w:document>"
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


def _p(*runs: str, style: str = "", list_item: bool = False) -> str:
    inner = ""
    if style:
        inner += f'<w:pStyle w:val="{style}"/>'
    if list_item:
        inner += "<w:numPr><w:ilvl w:val=\"0\"/><w:numId w:val=\"1\"/></w:numPr>"
    ppr = f"<w:pPr>{inner}</w:pPr>" if inner else ""
    return f"<w:p>{ppr}{''.join(runs)}</w:p>"


def _r(text: str, bold: bool = False) -> str:
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f"<w:r>{rpr}<w:t xml:space=\"preserve\">{text}</w:t></w:r>"


class DocxReaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self._paths: list[str] = []

    def tearDown(self) -> None:
        for p in self._paths:
            Path(p).unlink(missing_ok=True)

    def _read(self, body_xml: str, rels_xml: str = "") -> docx_reader.Document:
        path = _docx(body_xml, rels_xml)
        self._paths.append(path)
        return docx_reader.read(path)

    def test_split_runs_join_into_one_sentence(self) -> None:
        # Word splits a highlighted keyword mid-sentence into 3 runs.
        body = _p(_r("Choose the "), _r("best work bag", bold=True), _r(" today"))
        doc = self._read(body)
        self.assertEqual(doc.paragraphs[0].text, "Choose the best work bag today")

    def test_bold_run_becomes_strong_in_html(self) -> None:
        body = _p(_r("Plain "), _r("loud", bold=True))
        self.assertEqual(self._read(body).paragraphs[0].html, "Plain <strong>loud</strong>")

    def test_is_bold_para_detects_typed_heading(self) -> None:
        doc = self._read(_p(_r("H2: A Section", bold=True)) + _p(_r("body prose")))
        self.assertTrue(doc.paragraphs[0].is_bold)
        self.assertFalse(doc.paragraphs[1].is_bold)

    def test_pstyle_exposed(self) -> None:
        doc = self._read(_p(_r("BrandA"), style="Heading3"))
        self.assertEqual(doc.paragraphs[0].style, "Heading3")

    def test_is_list_item_detects_numpr(self) -> None:
        doc = self._read(_p(_r("a bullet"), list_item=True) + _p(_r("plain")))
        self.assertTrue(doc.paragraphs[0].is_list_item)
        self.assertFalse(doc.paragraphs[1].is_list_item)

    def test_hyperlink_resolves_to_real_url(self) -> None:
        body = _p(
            _r("Visit "),
            f'<w:hyperlink r:id="rId7">{_r("our shop")}</w:hyperlink>',
        )
        rels = '<Relationship Id="rId7" Target="https://x.com/p?a=1&amp;b=2"/>'
        para = self._read(body, rels).paragraphs[0]
        self.assertEqual(para.html, 'Visit <a href="https://x.com/p?a=1&b=2">our shop</a>')
        self.assertIn("our shop", para.text)  # label still in plain text

    def test_hyperlink_leading_space_hoisted_out_of_anchor(self) -> None:
        # Google Docs sometimes exports the separating space as a run INSIDE the
        # hyperlink. It must render BEFORE the <a>, not inside the link text, or
        # the link glues to the previous word (invisible in CJK, broken in English).
        body = _p(
            _r("An"),
            f'<w:hyperlink r:id="rId7">{_r(" ")}{_r("ABN page")}</w:hyperlink>',
        )
        rels = '<Relationship Id="rId7" Target="https://x.com/abn"/>'
        para = self._read(body, rels).paragraphs[0]
        self.assertEqual(para.html, 'An <a href="https://x.com/abn">ABN page</a>')

    def test_hyperlink_trailing_space_hoisted_out_of_anchor(self) -> None:
        body = _p(
            f'<w:hyperlink r:id="rId7">{_r("ABN page")}{_r(" ")}</w:hyperlink>',
            _r("is required"),
        )
        rels = '<Relationship Id="rId7" Target="https://x.com/abn"/>'
        para = self._read(body, rels).paragraphs[0]
        self.assertEqual(para.html, '<a href="https://x.com/abn">ABN page</a> is required')

    def test_sdt_wrapped_paragraph_is_captured(self) -> None:
        # Word wraps a paragraph in <w:sdt> (a content control / structured tag)
        # when one is applied -- common on headings. read() must descend into
        # <w:sdtContent>, or the whole control is skipped and its text silently
        # vanishes (real bug: lost every heading in a content-control'd brief).
        body = (
            _p(_r("Intro paragraph"))
            + f"<w:sdt><w:sdtPr/><w:sdtContent>{_p(_r('H3: 2. A Heading'))}</w:sdtContent></w:sdt>"
            + _p(_r("Body after heading"))
        )
        texts = [p.text for p in self._read(body).paragraphs]
        self.assertEqual(texts, ["Intro paragraph", "H3: 2. A Heading", "Body after heading"])

    def test_sdt_wrapped_paragraph_in_cell_is_captured(self) -> None:
        tbl = (
            "<w:tbl><w:tr>"
            f"<w:tc>{_p(_r('VI. Body content'))}</w:tc>"
            f"<w:tc><w:sdt><w:sdtContent>{_p(_r('H2: Section'))}</w:sdtContent></w:sdt>"
            f"{_p(_r('prose'))}</w:tc>"
            "</w:tr></w:tbl>"
        )
        cell = self._read(tbl).tables[0].rows[0][1]
        self.assertEqual([p.text for p in cell.paras], ["H2: Section", "prose"])

    def test_inline_sdt_wrapped_run_appears_in_html(self) -> None:
        # Word wraps a run in an INLINE <w:sdt> (content control on a span, not
        # the whole paragraph). .html must descend into <w:sdtContent> or the
        # run -- its bold, its text -- vanishes (real bug: body paragraphs came
        # out empty because every run was sdt-wrapped). .text already recurses;
        # .html must too, so they stay consistent.
        run = _r("loud", bold=True)
        body = _p(f'<w:sdt><w:sdtPr/><w:sdtContent>{run}</w:sdtContent></w:sdt>')
        self.assertEqual(self._read(body).paragraphs[0].html, "<strong>loud</strong>")

    def test_inline_sdt_run_keeps_order_with_direct_runs(self) -> None:
        body = _p(
            _r("A "),
            f'<w:sdt><w:sdtContent>{_r("mid")}</w:sdtContent></w:sdt>',
            _r(" C"),
        )
        para = self._read(body).paragraphs[0]
        self.assertEqual(para.text, "A mid C")
        self.assertEqual(para.html, "A mid C")

    def test_table_label_and_cell_paragraphs(self) -> None:
        # A house-template field table: label cell + body cell with 2 paras.
        tbl = (
            "<w:tbl><w:tr>"
            f"<w:tc>{_p(_r('VI. Body content'))}</w:tc>"
            f"<w:tc>{_p(_r('H1: Title'))}{_p(_r('First paragraph'))}</w:tc>"
            "</w:tr></w:tbl>"
        )
        doc = self._read(tbl)
        self.assertEqual(len(doc.tables), 1)
        self.assertEqual(doc.tables[0].label, "VI. Body content")
        body_cell = doc.tables[0].rows[0][1]
        self.assertEqual([p.text for p in body_cell.paras], ["H1: Title", "First paragraph"])

    def test_nested_table_inside_cell(self) -> None:
        inner = "<w:tbl><w:tr><w:tc>" + _p(_r("08:00")) + "</w:tc></w:tr></w:tbl>"
        tbl = f"<w:tbl><w:tr><w:tc>{_p(_r('VI. Body content'))}</w:tc>" \
              f"<w:tc>{_p(_r('prose'))}{inner}</w:tc></w:tr></w:tbl>"
        cell = self._read(tbl).tables[0].rows[0][1]
        self.assertEqual(len(cell.tables), 1)
        self.assertEqual(cell.tables[0].rows[0][0].text, "08:00")

    def test_cell_blocks_preserve_para_table_order(self) -> None:
        inner = "<w:tbl><w:tr><w:tc>" + _p(_r("grid")) + "</w:tc></w:tr></w:tbl>"
        tbl = (
            "<w:tbl><w:tr>"
            f"<w:tc>{_p(_r('VI. Body content'))}</w:tc>"
            f"<w:tc>{_p(_r('before'))}{inner}{_p(_r('after'))}</w:tc>"
            "</w:tr></w:tbl>"
        )
        cell = self._read(tbl).tables[0].rows[0][1]
        kinds = [type(b).__name__ for b in cell.blocks]
        self.assertEqual(kinds, ["Para", "Table", "Para"])

    def test_block_order_preserved(self) -> None:
        body = _p(_r("intro")) + "<w:tbl><w:tr><w:tc>" + _p(_r("x")) + "</w:tc></w:tr></w:tbl>" + _p(_r("outro"))
        kinds = [type(b).__name__ for b in self._read(body).blocks]
        self.assertEqual(kinds, ["Para", "Table", "Para"])

    def test_doctype_is_rejected(self) -> None:
        # Billion-laughs guard: a DOCTYPE in document.xml must raise, not expand.
        document = (
            '<?xml version="1.0"?>'
            '<!DOCTYPE w:document [<!ENTITY lol "ha">]>'
            f"<w:document {_W} {_RNS}><w:body>{_p(_r('hi'))}</w:body></w:document>"
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", document)
        tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
        tmp.write(buf.getvalue())
        tmp.close()
        self._paths.append(tmp.name)
        with self.assertRaises(docx_reader.DocxError):
            docx_reader.read(tmp.name)

    def test_non_docx_raises(self) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
        tmp.write(b"this is not a zip")
        tmp.close()
        self._paths.append(tmp.name)
        with self.assertRaises(docx_reader.DocxError):
            docx_reader.read(tmp.name)


if __name__ == "__main__":
    unittest.main()