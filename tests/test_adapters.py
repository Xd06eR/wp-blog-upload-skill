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


if __name__ == "__main__":
    unittest.main()
