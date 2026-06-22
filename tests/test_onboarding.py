"""Tests for onboarding guards: /admin URL, editor honesty, slug collision.

Network is stubbed (no real WP). Workspace is redirected to a temp dir.
Run from the skill root:
    PYTHONPATH=. python3 -B -m unittest tests.test_onboarding -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.tools import onboarding, workspace
from scripts.tools.wp_client import WPCredentials, WPError, _normalize_site_root


class NormalizeSiteRootTest(unittest.TestCase):
    """H4: bare /admin is a legit subdir path and must NOT be stripped."""

    def test_wp_admin_stripped(self) -> None:
        self.assertEqual(_normalize_site_root("https://x.com/wp-admin"), "https://x.com")

    def test_wp_login_stripped(self) -> None:
        self.assertEqual(_normalize_site_root("https://x.com/wp-login.php"), "https://x.com")

    def test_bare_admin_preserved(self) -> None:
        self.assertEqual(_normalize_site_root("https://x.com/admin"), "https://x.com/admin")

    def test_subdir_install_preserved(self) -> None:
        self.assertEqual(_normalize_site_root("https://x.com/blog/"), "https://x.com/blog")


class HttpsGuardTest(unittest.TestCase):
    """L4: refuse http:// site URLs — basic auth would leak the app-password in cleartext."""

    def test_http_refused_for_nonlocalhost(self) -> None:
        from scripts.tools.onboarding import _assert_https
        for url in ("http://acme.com", "http://acme.com/wp-admin", "http://10.0.0.1"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError) as ctx:
                    _assert_https(url)
                self.assertIn("cleartext", str(ctx.exception).lower())

    def test_https_dev_and_schemeless_allowed(self) -> None:
        from scripts.tools.onboarding import _assert_https
        for url in ("https://acme.com", "https://acme.com/wp-admin",
                    "http://localhost", "http://127.0.0.1", "http://site.local",
                    "acme.com"):  # scheme-less — derive_slug treats as https
            with self.subTest(url=url):
                _assert_https(url)  # must not raise


class DetectEditorHonestyTest(unittest.TestCase):
    """H3: detect_editor reports whether it actually detected vs defaulted."""

    def _creds(self) -> WPCredentials:
        return WPCredentials(site_url="https://x.com", username="u", app_password="p")

    def test_gutenberg_detected(self) -> None:
        post = [{"content": {"raw": "<!-- wp:paragraph --><p>hi</p>"}}]
        with mock.patch.object(onboarding, "_wp_get", return_value=(200, json.dumps(post).encode())):
            self.assertEqual(onboarding.detect_editor(self._creds()), ("gutenberg", True))

    def test_classic_detected(self) -> None:
        post = [{"content": {"raw": "<p>plain html</p>"}}]
        with mock.patch.object(onboarding, "_wp_get", return_value=(200, json.dumps(post).encode())):
            self.assertEqual(onboarding.detect_editor(self._creds()), ("classic", True))

    def test_no_posts_defaults_not_detected(self) -> None:
        with mock.patch.object(onboarding, "_wp_get", return_value=(200, b"[]")):
            self.assertEqual(onboarding.detect_editor(self._creds()), ("gutenberg", False))

    def test_probe_error_defaults_not_detected(self) -> None:
        with mock.patch.object(onboarding, "_wp_get", side_effect=WPError("boom")):
            self.assertEqual(onboarding.detect_editor(self._creds()), ("gutenberg", False))


class SlugCollisionTest(unittest.TestCase):
    """C2: a second site deriving the same slug must not overwrite the first."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        ws = Path(self._tmp.name) / "blog-upload-workspace"
        # Patch root()/find() directly, NOT just _canonical_workspace: root()
        # searches downward then upward BEFORE the canonical fallback, so running
        # the suite from a directory at/above the real workspace would otherwise
        # resolve to it and write these test clients into the live secrets dir +
        # clients.db. Pinning root() forces every workspace path into the temp dir.
        self._root = mock.patch.object(workspace, "root", return_value=ws)
        self._find = mock.patch.object(workspace, "find", return_value=ws)
        self._root.start()
        self._find.start()
        # client_store memoizes a singleton keyed by db_path; clear it so this
        # test binds to the temp DB (and the next test isn't left on a stale one).
        import scripts.tools.client_store as client_store
        client_store._store = None
        self._client_store = client_store
        # stub the network: login ok, gutenberg detected
        self._login = mock.patch.object(onboarding, "_verify_login", return_value="Site")
        self._login.start()
        self._probe = mock.patch.object(
            onboarding, "detect_editor", return_value=("gutenberg", True))
        self._probe.start()
        # Materialize the temp workspace skeleton up-front so register_client's
        # ensure() is a no-op for .env.example. The write-failure test patches
        # Path.write_text and must intercept ONLY the credential write, not the
        # skeleton bootstrap (the old code leaned on the real workspace existing).
        workspace.ensure()

    def tearDown(self) -> None:
        self._probe.stop()
        self._login.stop()
        self._find.stop()
        self._root.stop()
        self._client_store._store = None
        self._tmp.cleanup()

    def _onboard(self, slug, site_url):
        return onboarding.register_client(
            slug=slug, site_url=site_url, username="u", app_password="p")

    def test_same_site_reonboard_allowed(self) -> None:
        self._onboard("acme", "https://acme.com/")
        # re-onboarding the SAME root is a credential refresh, not a collision
        self._onboard("acme", "https://acme.com/wp-admin")  # normalizes to same root
        self.assertTrue(onboarding.client_exists("acme"))

    def test_different_site_same_slug_refused(self) -> None:
        self._onboard("acme", "https://acme.com/")
        with self.assertRaises(WPError) as cm:
            self._onboard("acme", "https://acme.org/")  # different root, same slug
        self.assertIn("already registered", str(cm.exception))

    def test_explicit_slug_disambiguates(self) -> None:
        self._onboard("acme", "https://acme.com/")
        self._onboard("acme-org", "https://acme.org/")  # explicit distinct slug
        self.assertTrue(onboarding.client_exists("acme"))
        self.assertTrue(onboarding.client_exists("acme-org"))

    def test_creds_file_cleaned_up_on_write_failure(self) -> None:
        # M2: a chmod/write failure must not leave a plaintext credential file.
        from pathlib import Path as _P
        with mock.patch.object(_P, "write_text", side_effect=OSError("read-only fs")):
            with self.assertRaises(WPError):
                self._onboard("acme", "https://acme.com/")
        secrets = workspace.secrets_dir()
        self.assertFalse((secrets / "acme.json").exists())


if __name__ == "__main__":
    unittest.main()
