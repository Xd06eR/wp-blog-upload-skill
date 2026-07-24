"""Tests for the verbatim HTML upload path (upload_html).

A finished .html blog is POSTed to WP `content` byte-for-byte — no parser, no
adapter, no re-clean — so TOC anchor links and heading ids survive. The first
<h1> is lifted into the post title and dropped from the body (WP renders the
title as the page H1; leaving it would double-title). The WP client is stubbed
so no network call is made.

Run from the skill root:
    PYTHONPATH=. python3 -B -m unittest tests.test_upload_html -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import upload_blog
from scripts.tools.client_config import ClientConfig

# A trimmed stand-in for the real reference article: H1 title, TOC with jump
# links, and matching anchored headings.
_HTML = (
    "<h1>What Is GEO?</h1>\n"
    '<h2 id="table-of-contents">Table of Contents</h2>\n'
    "<ul>\n"
    '  <li><a href="#what-is-geo">What Is GEO?</a></li>\n'
    '  <li><a href="#faq">FAQ</a></li>\n'
    "</ul>\n"
    '<h2 id="what-is-geo">What Is GEO?</h2>\n'
    "<p>Body paragraph with a <strong>bold</strong> bit.</p>\n"
    '<h2 id="faq">FAQ</h2>\n'
    "<p>Answer.</p>\n"
)


class _FakeWP:
    """Minimal WPClient stand-in: records the posted payload, fakes IDs."""

    def __init__(self) -> None:
        self.created_payload: dict | None = None
        self.uploaded: list[tuple[str, str]] = []
        self._media_id = 100
        self._tag_id = 0

    def upload_media(self, image_path, alt_text: str = "") -> dict:
        self.uploaded.append((str(image_path), alt_text))
        self._media_id += 1
        return {
            "id": self._media_id,
            "source_url": f"https://example.test/uploads/{Path(image_path).name}",
        }

    def find_category_id(self, slug: str):
        return None

    def find_or_create_tag(self, name: str) -> int:
        self._tag_id += 1
        return self._tag_id

    def create_post(self, payload: dict) -> dict:
        self.created_payload = payload
        return {"id": 42, "link": "https://x.example/?p=42"}


def _cfg(title_template: str = "{h1}", default_tags=None) -> ClientConfig:
    return ClientConfig(
        slug="acme", display_name="Acme", primary_domain="acme.example",
        wp_base_url="https://acme.example", wp_credentials_path="/dev/null",
        editor="classic", title_template=title_template,
        default_tags=default_tags or [],
    )


class UploadHtmlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.wp = _FakeWP()
        self._creds = mock.patch.object(
            upload_blog.WPCredentials, "load",
            return_value=mock.Mock(site_base="https://acme.example"),
        )
        self._wpc = mock.patch.object(upload_blog, "WPClient", return_value=self.wp)
        self._creds.start()
        self._wpc.start()

    def tearDown(self) -> None:
        self._wpc.stop()
        self._creds.stop()

    def _run(self, html, **kw):
        return upload_blog.upload_html(html, _cfg(kw.pop("cfg_template", "{h1}")), **kw)

    def test_h1_becomes_title_and_is_stripped_from_body(self) -> None:
        r = self._run(_HTML)
        self.assertEqual(r.title, "What Is GEO?")
        content = self.wp.created_payload["content"]
        self.assertNotIn("<h1>", content)  # title H1 removed
        self.assertIn("<p>Body paragraph", content)  # rest of body kept

    def test_toc_anchors_preserved_verbatim(self) -> None:
        self._run(_HTML)
        content = self.wp.created_payload["content"]
        # Both the jump link and its target id must survive byte-for-byte.
        self.assertIn('<h2 id="what-is-geo">', content)
        self.assertIn('<a href="#what-is-geo">', content)
        self.assertIn('<h2 id="faq">', content)
        self.assertIn('<a href="#faq">', content)
        # Inline markup untouched too.
        self.assertIn("<strong>bold</strong>", content)

    def test_status_is_draft(self) -> None:
        self._run(_HTML)
        self.assertEqual(self.wp.created_payload["status"], "draft")

    def test_empty_html_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._run("")

    def test_whitespace_only_html_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._run("   \n\t  ")

    def test_h1_only_html_raises_empty_body(self) -> None:
        # H1 is stripped into the title; nothing else is left to post.
        with self.assertRaises(ValueError):
            self._run("<h1>Just a title</h1>")

    def test_no_h1_uses_fallback_title(self) -> None:
        r = self._run("<p>Body only.</p>", fallback_title="my-article")
        self.assertEqual(r.title, "my-article")
        self.assertIn("<p>Body only.</p>", self.wp.created_payload["content"])

    def test_title_arg_overrides_h1_and_h1_still_stripped(self) -> None:
        r = self._run(_HTML, title="Custom Title")
        self.assertEqual(r.title, "Custom Title")
        self.assertNotIn("<h1>", self.wp.created_payload["content"])

    def test_title_template_applied(self) -> None:
        r = upload_blog.upload_html(_HTML, _cfg("{h1} | Acme"))
        self.assertEqual(r.title, "What Is GEO? | Acme")

    def test_body_wrapper_inner_extracted(self) -> None:
        doc = (
            "<html><head><title>x</title><style>p{color:red}</style></head>"
            "<body><h1>T</h1><p>Real body.</p></body></html>"
        )
        self._run(doc)
        content = self.wp.created_payload["content"]
        self.assertIn("<p>Real body.</p>", content)
        self.assertNotIn("<style>", content)  # head chrome dropped
        self.assertNotIn("<body>", content)

    def test_bare_fragment_is_verbatim_apart_from_h1(self) -> None:
        html = "<h1>T</h1>\n<p>One.</p>\n<p>Two.</p>\n"
        self._run(html)
        content = self.wp.created_payload["content"]
        # Everything after the H1 element is preserved exactly.
        self.assertEqual(content.replace("<h1>T</h1>", "").strip(),
                         "<p>One.</p>\n<p>Two.</p>")

    def test_media_dir_sets_featured_without_appending_to_body(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            for name in ("b.png", "a.jpg"):
                (Path(d) / name).write_bytes(b"\x89PNG\r\n")
            r = self._run(_HTML, media_dir=d)
        # First image (name-sorted) is the featured image.
        self.assertEqual(self.wp.created_payload["featured_media"], 101)
        self.assertEqual(len(r.media), 2)
        # Body HTML must NOT gain any image markup — it stays the finished blog.
        content = self.wp.created_payload["content"]
        self.assertNotIn("<img", content)
        self.assertNotIn("wp:image", content)


if __name__ == "__main__":
    unittest.main()
