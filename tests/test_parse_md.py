"""Tests for parse_md brief parsing -- markdown backslash-escape handling.

Run from the skill root:
    PYTHONPATH=. python3 -B -m unittest tests.test_parse_md -v

Pure stdlib (unittest + tempfile) -- no pip, matching the skill's philosophy.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.tools import parse_md


# A brief whose H1 + body contain Google-Docs-style over-escaped punctuation:
#   F\&B   (escaped ampersand)   -> should render F&B
#   1\.    (escaped period)      -> should render 1.
# plus a raw (unescaped) ampersand and a link, which must survive untouched.
_BRIEF = """\
| Content Topic | Margin Tips |
| :---- | :---- |
| **URL** | https://example.com/blog/margins |
| **Meta Title** | 9 Ways F\\&B Operators Win |
| **H1** | 9 Margin Tips for Singapore F\\&B Operators |
| **Word count** | 100 words |

**H1: 9 Margin Tips for Singapore F\\&B Operators**

Singapore's F\\&B sector is tough. Read [our guide](https://example.com/g?a=1&b=2) now.

**H2: 1\\. Cut Food Waste**

Track waste & costs daily.
"""


class UnescapeMarkdownTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        )
        tmp.write(_BRIEF)
        tmp.close()
        self.path = tmp.name
        self.doc = parse_md.parse(self.path)

    def tearDown(self) -> None:
        Path(self.path).unlink(missing_ok=True)

    def _paragraphs(self) -> str:
        return " ".join(b.text for b in self.doc.body if b.kind == "paragraph")

    def test_title_drops_escaped_ampersand(self) -> None:
        # The reported bug: "F\&B" leaked into the WP post title.
        self.assertEqual(self.doc.title, "9 Margin Tips for Singapore F&B Operators")
        self.assertNotIn("\\", self.doc.title)

    def test_body_paragraph_unescapes_ampersand(self) -> None:
        joined = self._paragraphs()
        self.assertIn("F&B sector", joined)
        self.assertNotIn("F\\&B", joined)

    def test_links_survive_unescape(self) -> None:
        # Reordering unescape after link rendering must not corrupt the <a>.
        self.assertIn(
            '<a href="https://example.com/g?a=1&b=2">our guide</a>',
            self._paragraphs(),
        )

    def test_numbered_heading_dot_still_unescaped(self) -> None:
        # Regression guard: pre-existing "\." -> "." behavior must hold.
        h2s = [b.text for b in self.doc.body if b.kind == "h2"]
        self.assertIn("1. Cut Food Waste", h2s)

    def test_raw_ampersand_preserved(self) -> None:
        # A real (unescaped) ampersand must pass through unchanged.
        self.assertIn("Track waste & costs daily.", self._paragraphs())


if __name__ == "__main__":
    unittest.main()
