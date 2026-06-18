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


_VARIANT_BRIEF = """\
| Content Topic | Variants |
| :---- | :---- |
| **URL** | https://example.com/v |
| **H1** | Main Title |
| **Word count** | 100 words |

**H1: Main Title**

Intro.

**H2： 全形冒號標題**

中文內文。

**H3. 1. Numbered French Sub**

Body.

#### **H4 : Hash Wrapped**

More body.
"""


class KeywordCleanerTest(unittest.TestCase):
    """H7: keyword cell -> clean list (label, volumes, separators)."""

    def test_strips_blog_keywords_label(self) -> None:
        self.assertEqual(parse_md.clean_keywords("Blog Keywords: alpha, beta"), ["alpha", "beta"])

    def test_drops_search_volume_integers(self) -> None:
        out = parse_md.clean_keywords("part time mba hong kong 70, hk mba 10")
        self.assertEqual(out, ["part time mba hong kong", "hk mba"])

    def test_keeps_cjk_phrase_with_spaces_intact(self) -> None:
        # whitespace is NOT a separator -- a comma-less CJK cell stays one phrase.
        self.assertEqual(parse_md.clean_keywords("中西式 婚禮"), ["中西式 婚禮"])

    def test_splits_on_comma_semicolon_newline(self) -> None:
        self.assertEqual(parse_md.clean_keywords("a, b; c\nd"), ["a", "b", "c", "d"])


class StripInlineMdTest(unittest.TestCase):
    """M8: global bold strip, not a single outer pair."""

    def test_two_bold_runs(self) -> None:
        self.assertEqual(parse_md._strip_inline_md("**a** and **b**"), "a and b")

    def test_bold_italic(self) -> None:
        self.assertEqual(parse_md._strip_inline_md("***x***"), "x")


class LinkParenTest(unittest.TestCase):
    """M9: URL containing balanced parens is not truncated."""

    def test_paren_url_survives(self) -> None:
        out = parse_md._convert_inline("see [doc](https://x.com/a_(b)_c) now")
        self.assertIn('href="https://x.com/a_(b)_c"', out)


class BrandHeaderHashTest(unittest.TestCase):
    """H8: a brand header after a stray empty `### ` keeps a clean name."""

    def test_hash_not_pulled_into_brand_name(self) -> None:
        text = "### \n\n### KitchenPark (AR)\n\n| Content Topic | x |\n| :- | :- |\n| **URL** | u |\n"
        names = [b.brand for b in parse_md.list_briefs(_tmp_md(text))]
        self.assertIn("KitchenPark (AR)", names)
        self.assertNotIn("### KitchenPark (AR)", names)


def _tmp_md(text: str) -> str:
    t = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
    t.write(text)
    t.close()
    return t.name


class HeadingVariantTest(unittest.TestCase):
    """B1: heading detection across colon / full-width / period / hash forms."""

    def setUp(self) -> None:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
        tmp.write(_VARIANT_BRIEF)
        tmp.close()
        self.path = tmp.name
        self.doc = parse_md.parse(self.path)

    def tearDown(self) -> None:
        Path(self.path).unlink(missing_ok=True)

    def test_full_width_colon_heading_detected(self) -> None:
        h2 = [b.text for b in self.doc.body if b.kind == "h2"]
        self.assertIn("全形冒號標題", h2)

    def test_period_numbered_heading_detected(self) -> None:
        h3 = [b.text for b in self.doc.body if b.kind == "h3"]
        self.assertIn("1. Numbered French Sub", h3)

    def test_hash_wrapped_heading_detected(self) -> None:
        h4 = [b.text for b in self.doc.body if b.kind == "h4"]
        self.assertIn("Hash Wrapped", h4)

    def test_no_heading_leaks_into_paragraphs(self) -> None:
        paras = " ".join(b.text for b in self.doc.body if b.kind == "paragraph")
        self.assertNotIn("全形冒號標題", paras)
        self.assertNotIn("Numbered French Sub", paras)


if __name__ == "__main__":
    unittest.main()
