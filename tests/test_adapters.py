"""Tests for the editor adapters (gutenberg / classic / elementor).

Focus: table-block rendering (A4) -- the in-body schedule/comparison
grids must become valid <table> markup, never <p><table></p>.
Run from the skill root:
    PYTHONPATH=. python3 -B -m unittest tests.test_adapters -v
"""

from __future__ import annotations

import json
import unittest

from scripts import adapters
from scripts.adapters._escape import build_todo_meta, comment_safe, escape_inline
from scripts.tools.parse_md import Block, Brief, ParsedDoc


def _doc(*blocks: Block) -> ParsedDoc:
    return ParsedDoc(brief=Brief(), body=list(blocks), title="T", brand="")


_TABLE = Block(kind="table", rows=[["Time", "Event"], ["08:00", "Tea ceremony"]])


class TableRenderTest(unittest.TestCase):
    def test_gutenberg_emits_wp_table_not_p_table(self) -> None:
        out = adapters.get("gutenberg")(_doc(_TABLE))
        self.assertIn("<!-- wp:table -->", out)
        self.assertIn("<table>", out)
        self.assertIn("<th>Time</th>", out)
        self.assertIn("<td>08:00</td>", out)
        self.assertNotIn("<p><table", out)  # the invalid shape we are avoiding

    def test_classic_emits_table(self) -> None:
        out = adapters.get("classic")(_doc(_TABLE))
        self.assertIn("<table>", out)
        self.assertIn("<thead><tr><th>Time</th><th>Event</th></tr></thead>", out)
        self.assertIn("<td>Tea ceremony</td>", out)

    def test_elementor_table_in_fallback_and_widget(self) -> None:
        envelope = json.loads(adapters.get("elementor")(_doc(_TABLE)))
        self.assertIn("<table>", envelope["content"])
        data = json.loads(envelope["meta"]["_elementor_data"])
        # the table widget carries the <table> in its text-editor settings
        widget = data[0]["elements"][0]["elements"][0]
        self.assertEqual(widget["widgetType"], "text-editor")
        self.assertIn("<table>", widget["settings"]["editor"])

    def test_empty_table_renders_nothing(self) -> None:
        out = adapters.get("classic")(_doc(Block(kind="table", rows=[])))
        self.assertNotIn("<table>", out)


class EscapeInlineTest(unittest.TestCase):
    """C3: escape literal spans but keep inline tags + valid hrefs."""

    def test_amp_beside_link_is_escaped(self) -> None:
        out = escape_inline('F&B and <a href="https://x.com/a?u=1&b=2">shop</a> Q&A')
        # literal ampersands -> entities ...
        self.assertIn("F&amp;B", out)
        self.assertIn("Q&amp;A", out)
        # ... and the href ampersand is also a valid entity, tag preserved
        self.assertIn('<a href="https://x.com/a?u=1&amp;b=2">shop</a>', out)

    def test_plain_text_fully_escaped(self) -> None:
        self.assertEqual(escape_inline("1 < 2 & 3 > 0"), "1 &lt; 2 &amp; 3 &gt; 0")

    def test_strong_tag_preserved(self) -> None:
        self.assertEqual(escape_inline("see <strong>F&B</strong>"), "see <strong>F&amp;B</strong>")

    def test_existing_entity_not_double_escaped(self) -> None:
        self.assertEqual(escape_inline("a &amp; b"), "a &amp; b")


class AdapterEscapingTest(unittest.TestCase):
    """The C3 bug end-to-end: a block mixing a link with raw & must not ship raw &."""

    def _para(self) -> Block:
        return Block(kind="paragraph",
                     text='Visit <a href="https://x.com/?a=1&b=2">us</a> for F&B tips')

    def test_gutenberg_paragraph_escapes_around_link(self) -> None:
        out = adapters.get("gutenberg")(_doc(self._para()))
        self.assertIn("F&amp;B", out)
        self.assertIn('href="https://x.com/?a=1&amp;b=2"', out)
        self.assertNotIn("F&B tips", out)  # the raw form must be gone

    def test_classic_paragraph_escapes_around_link(self) -> None:
        out = adapters.get("classic")(_doc(self._para()))
        self.assertIn("F&amp;B", out)
        self.assertIn('href="https://x.com/?a=1&amp;b=2"', out)


class TodoMetaCommentTest(unittest.TestCase):
    """C4: a `-->` in a meta field must not break out of the hidden comment."""

    def _doc_with_meta(self) -> ParsedDoc:
        brief = Brief(meta_title="Cheap flights --> book now",
                      meta_description="Save 50% --> limited", page_url="https://x.com")
        return ParsedDoc(brief=brief, body=[Block(kind="paragraph", text="body")], title="T")

    def test_comment_safe_neutralizes_close(self) -> None:
        self.assertNotIn("-->", comment_safe("a --> b"))

    def test_builder_meta_close_is_only_terminator(self) -> None:
        out = build_todo_meta(self._doc_with_meta().brief)
        self.assertEqual(out.count("-->"), 1)  # the meta `-->` was neutralized
        self.assertTrue(out.rstrip().endswith("-->"))

    def test_classic_meta_does_not_leak_into_body(self) -> None:
        # Classic emits no wp: block comments, so the comment terminator is
        # unambiguous: the meta breakout must not have created a second one.
        out = adapters.get("classic")(self._doc_with_meta())
        self.assertEqual(out.count("-->"), 1)
        self.assertLess(out.index("-->"), out.index("<p>body</p>"))

    def test_no_adapter_leaks_raw_meta_breakout(self) -> None:
        for editor in ("gutenberg", "classic", "elementor"):
            out = adapters.get(editor)(self._doc_with_meta())
            # the raw "--> book now" run that would escape the comment is gone
            self.assertNotIn("--> book now", out)
            self.assertNotIn("--> limited", out)


if __name__ == "__main__":
    unittest.main()
