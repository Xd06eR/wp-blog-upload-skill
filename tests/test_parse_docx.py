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


def _li(text: str) -> str:
    """A Word native list-item paragraph (<w:numPr>)."""
    return ('<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/>'
            f'</w:numPr></w:pPr>{_r(text)}</w:p>')


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


# A single-body house brief mirroring the common house-template export shape, including the
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

    def test_consecutive_list_items_grouped_into_one_list_block(self) -> None:
        body = (
            _p(_r("H1: T", bold=True))
            + _p(_r("Consider this if you:"))
            + _li("first reason")
            + _li("second reason")
            + _li("third reason")
            + _p(_r("Closing paragraph."))
        )
        doc = parse_docx.parse(self._write(_house_body(body)))
        kinds = [b.kind for b in doc.body]
        self.assertEqual(kinds, ["paragraph", "list", "paragraph"])
        listb = doc.body[1]
        self.assertEqual(listb.items, ["first reason", "second reason", "third reason"])

    def test_separated_list_items_form_separate_lists(self) -> None:
        body = (
            _p(_r("H1: T", bold=True))
            + _li("group one item")
            + _p(_r("interrupting prose"))
            + _li("group two item")
        )
        doc = parse_docx.parse(self._write(_house_body(body)))
        lists = [b for b in doc.body if b.kind == "list"]
        self.assertEqual(len(lists), 2)


class ParseDocxInBodyTableTest(unittest.TestCase):
    """A nested Word table inside the body cell -> a `table` Block, in order."""

    def setUp(self) -> None:
        self._paths: list[str] = []

    def tearDown(self) -> None:
        for p in self._paths:
            Path(p).unlink(missing_ok=True)

    def test_nested_table_becomes_table_block_in_position(self) -> None:
        nested = _table(
            _row(_cell(_p(_r("Time"))), _cell(_p(_r("Event")))),
            _row(_cell(_p(_r("08:00"))), _cell(_p(_r("Tea ceremony")))),
        )
        body = (
            _p(_r("H1: Wedding", bold=True))
            + _p(_r("Before the table."))
            + nested
            + _p(_r("After the table."))
        )
        path = _docx(_house_body(body))
        self._paths.append(path)
        doc = parse_docx.parse(path)
        kinds = [b.kind for b in doc.body]
        self.assertEqual(kinds, ["paragraph", "table", "paragraph"])
        tbl = doc.body[1]
        self.assertEqual(tbl.rows, [["Time", "Event"], ["08:00", "Tea ceremony"]])


def _h3(text: str) -> str:
    return f'<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr>{_r(text)}</w:p>'


class ParseDocxMultiBodyTest(unittest.TestCase):
    """One .docx, several VI. Body content tables (the 6-blog translation shape)."""

    def setUp(self) -> None:
        self._paths: list[str] = []
        # Topic with a ZH original (full meta) + an EN translation (IV/V only,
        # inherits the ZH page_url + word count).
        zh = (
            self._page_url("https://shop.example/", "800")
            + _field("II. Keyword(s) for the page", "kw a kw b")
            + _field("IV. Page title", "中文標題")
            + _field("V. Meta description", "中文描述")
            + self._body(_p(_r("H1: 中文標題", bold=True)) + _p(_r("中文內文")))
        )
        en = (
            _field("IV. Page title", "English Title")
            + _field("V. Meta description", "English desc")
            + self._body(_p(_r("H1: English Title", bold=True)) + _p(_r("English body")))
        )
        self.path = _docx(zh + en)
        self._paths.append(self.path)

    def tearDown(self) -> None:
        for p in self._paths:
            Path(p).unlink(missing_ok=True)

    @staticmethod
    def _page_url(url: str, wc: str) -> str:
        return _table(
            _row(_cell(_p(_r("I. Page URL"))), _cell(_p(_r("Page Type"))), _cell(_p(_r("Word Count")))),
            _row(_cell(_p(_r(url))), _cell(_p(_r("New"))), _cell(_p(_r(wc)))),
        )

    @staticmethod
    def _body(paras: str) -> str:
        return _table(_row(_cell(_p(_r("VI. Body content")))), _row(_cell(paras)))

    def test_list_briefs_returns_all_bodies(self) -> None:
        briefs = parse_docx.list_briefs(self.path)
        self.assertEqual(len(briefs), 2)
        self.assertEqual([b.brand for b in briefs], ["中文標題", "English Title"])

    def test_no_brand_raises_with_choices(self) -> None:
        with self.assertRaises(ParseError) as cm:
            parse_docx.parse(self.path)
        self.assertIn("2 body sections", str(cm.exception))

    def test_select_zh_body(self) -> None:
        doc = parse_docx.parse(self.path, brand="中文標題")
        self.assertEqual(doc.title, "中文標題")
        self.assertEqual(doc.brief.page_url, "https://shop.example/")

    def test_translation_inherits_source_url(self) -> None:
        doc = parse_docx.parse(self.path, brand="English Title")
        self.assertEqual(doc.title, "English Title")
        # EN block has no I. Page URL of its own -> inherits the ZH sibling's.
        self.assertEqual(doc.brief.page_url, "https://shop.example/")
        self.assertEqual(doc.brief.word_count, "800")


class ParseDocxParagraphStreamTest(unittest.TestCase):
    """No body table; Heading3 brand markers with body in the paragraph stream."""

    def setUp(self) -> None:
        self._paths: list[str] = []
        body = (
            _h3("BrandA (EN)")
            + _p(_r("H1: Example Topic", bold=True))
            + _p(_r("Intro for brand A."))
            + _p(_r("H2: Why automate", bold=True))
            + _p(_r("Because speed."))
            + _h3("")  # empty placeholder brand header (no body) -> skipped
            + _h3("BrandB (ZH)")
            + _p(_r("H1: 廚房自動化", bold=True))
            + _p(_r("導言。"))
        )
        self.path = _docx(body)
        self._paths.append(self.path)

    def tearDown(self) -> None:
        for p in self._paths:
            Path(p).unlink(missing_ok=True)

    def test_list_briefs_skips_empty_brand(self) -> None:
        briefs = parse_docx.list_briefs(self.path)
        self.assertEqual([b.brand for b in briefs], ["BrandA (EN)", "BrandB (ZH)"])

    def test_no_brand_raises(self) -> None:
        with self.assertRaises(ParseError):
            parse_docx.parse(self.path)

    def test_select_brand_extracts_only_its_body(self) -> None:
        doc = parse_docx.parse(self.path, brand="BrandA (EN)")
        self.assertEqual(doc.title, "Example Topic")
        texts = " ".join(b.text for b in doc.body)
        self.assertIn("Because speed.", texts)
        self.assertNotIn("廚房自動化", texts)  # next brand's body must not bleed in

    def test_select_second_brand(self) -> None:
        doc = parse_docx.parse(self.path, brand="BrandB (ZH)")
        self.assertEqual(doc.title, "廚房自動化")

    def test_brand_with_body_but_no_h1_falls_back_to_brand_name(self) -> None:
        # A body with H2/H3 but the H1 living outside the stream (a styled line).
        body = (
            _h3("BrandC (FR)")
            + _p(_r("Intro sans titre."))
            + _p(_r("H2 : Une section", bold=True))
            + _p(_r("Corps."))
        )
        path = _docx(body)
        self._paths.append(path)
        doc = parse_docx.parse(path, brand="BrandC (FR)")
        self.assertEqual(doc.title, "BrandC (FR)")
        self.assertEqual([b.kind for b in doc.body], ["paragraph", "h2", "paragraph"])

    def test_brand_with_no_body_raises(self) -> None:
        body = _h3("EmptyBrand") + _h3("NextBrand") + _p(_r("H1: Next", bold=True)) + _p(_r("x"))
        path = _docx(body)
        self._paths.append(path)
        with self.assertRaises(ParseError):
            parse_docx.parse(path, brand="EmptyBrand")


if __name__ == "__main__":
    unittest.main()