"""Tests for upload_blog guards: title template, empty body, tag-length cap.

The WP REST client is stubbed so no network call is made.
Run from the skill root:
    PYTHONPATH=. python3 -B -m unittest tests.test_upload_blog -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import upload_blog
from scripts.tools.client_config import ClientConfig
from scripts.tools.parse_md import Block, Brief, ParsedDoc
from scripts.tools.wp_client import WPError


class _FakeWP:
    """Minimal WPClient stand-in: records the posted payload, fakes IDs."""

    def __init__(self) -> None:
        self.created_payload: dict | None = None
        self._tag_id = 0
        self.uploaded: list[tuple[str, str]] = []
        self._media_id = 100
        self.fail_paths: set[str] = set()

    def upload_media(self, image_path, alt_text: str = "") -> dict:
        # Raise the real error type so _resolve_media's "warn, don't abort" path
        # is exercised exactly as it would be against a live site.
        if str(image_path) in self.fail_paths:
            raise WPError(f"simulated upload failure: {image_path}")
        self.uploaded.append((str(image_path), alt_text))
        self._media_id += 1
        return {
            "id": self._media_id,
            "source_url": f"https://example.test/wp-content/uploads/{Path(image_path).name}",
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
    def test_empty_body_raises_not_warns(self) -> None:
        # An empty body must fail loud (ValueError), NOT post a blank draft.
        # SKILL.md contract: "fails with a clear error rather than posting a
        # blank draft." Both the .docx/.md and upload-prepared paths route
        # through _post_parsed_doc, so the guard here covers both.
        with self.assertRaises(ValueError) as ctx:
            self._run(_cfg(), _doc(body=[]))
        self.assertIn("empty body", str(ctx.exception).lower())

    def test_non_empty_body_no_warning(self) -> None:
        r = self._run(_cfg(), _doc())
        self.assertEqual(r.warnings, [])

    # Tags -----------------------------------------------------------------
    def test_keywords_are_not_tagged(self) -> None:
        # Brief Keywords must never become WP tags -- not even clean short
        # ones -- and must raise no tag-related warning.
        junk = "x " * 40  # ~80 chars; old code would have warned + skipped this
        r = self._run(_cfg(), _doc(keywords=[junk, "real tag"]))
        self.assertNotIn("tags", self.wp.created_payload)
        self.assertEqual(r.warnings, [])

    def test_default_tags_still_applied(self) -> None:
        # The client's curated default_tags survive; brief keywords are ignored.
        r = self._run(_cfg(default_tags=["brand"]), _doc(keywords=["alpha", "beta"]))
        self.assertEqual(self.wp.created_payload["tags"], [1])
        self.assertEqual(r.warnings, [])

    def test_status_is_always_draft(self) -> None:
        self._run(_cfg(), _doc())
        self.assertEqual(self.wp.created_payload["status"], "draft")


class ImageUploadTest(unittest.TestCase):
    """Image blocks are uploaded via the WP client; first becomes featured."""

    def setUp(self) -> None:
        self.wp = _FakeWP()
        self._creds = mock.patch.object(
            upload_blog.WPCredentials, "load",
            return_value=mock.Mock(site_base="https://example.test"),
        )
        self._wpc = mock.patch.object(upload_blog, "WPClient", return_value=self.wp)
        self._creds.start()
        self._wpc.start()

    def tearDown(self) -> None:
        self._wpc.stop()
        self._creds.stop()

    def _run(self, doc):
        return upload_blog._post_parsed_doc(doc, _cfg())

    def test_image_blocks_uploaded_and_first_is_featured(self) -> None:
        body = [
            Block(kind="image", src="/imgs/a.jpg", alt="one"),
            Block(kind="paragraph", text="hi"),
            Block(kind="image", src="/imgs/b.jpg", alt="two"),
        ]
        r = self._run(_doc(body=body))
        self.assertEqual(self.wp.uploaded, [("/imgs/a.jpg", "one"), ("/imgs/b.jpg", "two")])
        self.assertEqual(self.wp.created_payload["featured_media"], 101)  # first id
        self.assertEqual(len(r.media), 2)
        self.assertEqual(r.media[0]["id"], 101)

    def test_no_images_means_no_featured_media(self) -> None:
        r = self._run(_doc())
        self.assertNotIn("featured_media", self.wp.created_payload)
        self.assertEqual(r.media, [])

    def test_failed_image_warns_but_post_still_created(self) -> None:
        self.wp.fail_paths = {"/imgs/bad.jpg"}
        body = [
            Block(kind="image", src="/imgs/bad.jpg", alt="x"),
            Block(kind="image", src="/imgs/ok.jpg", alt="y"),
        ]
        r = self._run(_doc(body=body))
        self.assertIsNotNone(self.wp.created_payload)  # not aborted
        self.assertTrue(any("Image upload failed" in w for w in r.warnings))
        self.assertEqual(len(r.media), 1)  # only the good one
        self.assertEqual(self.wp.created_payload["featured_media"], 101)


class PreparedImageTest(unittest.TestCase):
    """upload-prepared body[] accepts image blocks for precise agent placement."""

    def test_payload_accepts_image_block(self) -> None:
        doc = upload_blog._payload_to_parsed_doc({
            "title": "T",
            "body": [{"kind": "image", "src": "/x/a.jpg", "alt": "A"}],
        })
        block = doc.body[0]
        self.assertEqual(block.kind, "image")
        self.assertEqual(block.src, "/x/a.jpg")
        self.assertEqual(block.alt, "A")

    def test_image_block_requires_src(self) -> None:
        with self.assertRaises(ValueError):
            upload_blog._payload_to_parsed_doc({
                "title": "T",
                "body": [{"kind": "image", "alt": "no src"}],
            })


class MediaDirTest(unittest.TestCase):
    """--media-dir synthesizes image blocks from a folder, name-sorted."""

    def test_blocks_built_in_name_order_skipping_non_images(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            for name in ("b.png", "a.jpg", "notes.txt", "c.jpeg"):
                (Path(d) / name).write_bytes(b"\x89PNG\r\n")
            blocks = upload_blog._media_dir_blocks(d)
        self.assertEqual([b.kind for b in blocks], ["image", "image", "image"])
        self.assertEqual([Path(b.src).name for b in blocks], ["a.jpg", "b.png", "c.jpeg"])
        self.assertEqual(blocks[0].alt, "a")  # filename stem is the placeholder alt

    def test_not_a_directory_raises(self) -> None:
        with self.assertRaises(ValueError):
            upload_blog._media_dir_blocks("/no/such/media/dir")


if __name__ == "__main__":
    unittest.main()
