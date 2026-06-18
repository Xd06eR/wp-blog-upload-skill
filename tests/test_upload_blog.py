"""Tests for upload_blog guards: title template, empty body, tag-length cap.

The WP REST client is stubbed so no network call is made.
Run from the skill root:
    PYTHONPATH=. python3 -B -m unittest tests.test_upload_blog -v
"""

from __future__ import annotations

import unittest
from unittest import mock

from scripts import upload_blog
from scripts.tools.client_config import ClientConfig
from scripts.tools.parse_md import Block, Brief, ParsedDoc


class _FakeWP:
    """Minimal WPClient stand-in: records the posted payload, fakes IDs."""

    def __init__(self) -> None:
        self.created_payload: dict | None = None
        self._tag_id = 0

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


def _doc(*, body=None, keywords=None, title="Post Title") -> ParsedDoc:
    return ParsedDoc(
        brief=Brief(keywords=keywords or []),
        body=body if body is not None else [Block(kind="paragraph", text="hi")],
        title=title,
    )


class UploadGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.wp = _FakeWP()
        # patch the WP client + creds loader so _post_parsed_doc stays offline
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

    def _run(self, cfg, doc):
        return upload_blog._post_parsed_doc(doc, cfg)

    # M5 -------------------------------------------------------------------
    def test_title_template_applied(self) -> None:
        r = self._run(_cfg("{h1} | Acme"), _doc(title="Hello"))
        self.assertEqual(r.title, "Hello | Acme")

    def test_bad_title_template_falls_back_to_h1(self) -> None:
        # an unsupported placeholder must not crash the upload
        r = self._run(_cfg("{h1} - {brand}"), _doc(title="Hello"))
        self.assertEqual(r.title, "Hello")

    def test_title_template_with_stray_braces(self) -> None:
        r = self._run(_cfg("use {} here"), _doc(title="Hello"))
        self.assertEqual(r.title, "Hello")

    # M6 -------------------------------------------------------------------
    def test_empty_body_warns(self) -> None:
        r = self._run(_cfg(), _doc(body=[]))
        self.assertTrue(any("empty body" in w for w in r.warnings))

    def test_non_empty_body_no_warning(self) -> None:
        r = self._run(_cfg(), _doc())
        self.assertEqual(r.warnings, [])

    # H7-downstream --------------------------------------------------------
    def test_overlong_keyword_skipped_as_tag(self) -> None:
        junk = "x " * 40  # ~80 chars, an un-delimited blob
        r = self._run(_cfg(), _doc(keywords=[junk, "real tag"]))
        # only the real tag became a WP tag
        self.assertEqual(self.wp.created_payload["tags"], [1])
        self.assertTrue(any("over-long keyword" in w for w in r.warnings))

    def test_normal_keywords_all_kept(self) -> None:
        r = self._run(_cfg(), _doc(keywords=["alpha", "beta"]))
        self.assertEqual(len(self.wp.created_payload["tags"]), 2)
        self.assertEqual(r.warnings, [])

    def test_status_is_always_draft(self) -> None:
        self._run(_cfg(), _doc())
        self.assertEqual(self.wp.created_payload["status"], "draft")


if __name__ == "__main__":
    unittest.main()
