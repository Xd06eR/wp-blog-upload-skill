"""Tests for move-safe credential paths in client_store.

Credential paths are stored RELATIVE to the workspace and resolved absolute
next to the clients.db at load time, so moving or renaming the workspace
folder never breaks credential lookup.

Run from the skill root:
    PYTHONPATH=. python3 -B -m unittest tests.test_client_store -v
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.tools.client_config import ClientConfig
from scripts.tools.client_store import ClientStore


def _cfg(slug: str = "acme") -> ClientConfig:
    return ClientConfig(
        slug=slug,
        display_name="Acme",
        primary_domain="acme.com",
        wp_base_url="https://acme.com",
        wp_credentials_path="/whatever/gets/normalized.json",
        editor="gutenberg",
    )


class CredentialPathTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = self.root / "data" / "clients.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _raw_stored(self, db: Path, slug: str = "acme") -> str | None:
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT wp_credentials_path FROM clients WHERE slug=?", (slug,)
        ).fetchone()
        con.close()
        return row["wp_credentials_path"] if row else None

    def test_stored_path_is_relative(self) -> None:
        store = ClientStore(self.db)
        store.save(_cfg())
        self.assertEqual(self._raw_stored(self.db), "data/secrets/acme.json")

    def test_loaded_path_is_absolute_next_to_db(self) -> None:
        store = ClientStore(self.db)
        store.save(_cfg())
        cfg = store.get("acme")
        self.assertEqual(
            cfg.wp_credentials_path, str(self.db.parent / "secrets" / "acme.json")
        )

    def test_load_ignores_garbage_stored_path(self) -> None:
        # A bogus stored value must still resolve to the derived location.
        store = ClientStore(self.db)
        store.save(_cfg())
        con = sqlite3.connect(self.db)
        con.execute("UPDATE clients SET wp_credentials_path='/nope/missing.json' WHERE slug='acme'")
        con.commit()
        con.close()
        cfg = store.get("acme")
        self.assertEqual(
            cfg.wp_credentials_path, str(self.db.parent / "secrets" / "acme.json")
        )

    def test_move_safe(self) -> None:
        # Save in one location, copy the db elsewhere, reopen: path follows the db.
        store = ClientStore(self.db)
        store.save(_cfg())
        new_root = self.root / "moved"
        (new_root / "data").mkdir(parents=True)
        shutil.copy(self.db, new_root / "data" / "clients.db")
        moved = ClientStore(new_root / "data" / "clients.db")
        cfg = moved.get("acme")
        self.assertEqual(
            cfg.wp_credentials_path, str(new_root / "data" / "secrets" / "acme.json")
        )


class MigrationV3Test(unittest.TestCase):
    """v3 drops the unused client-profile columns from a legacy (v2) db,
    without losing the client or its still-used fields."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "data" / "clients.db"
        self.db.parent.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_legacy_db(self) -> None:
        # A v2-shaped clients table carrying two of the soon-dropped columns.
        con = sqlite3.connect(self.db)
        con.executescript(
            """
            CREATE TABLE _schema_version (version INTEGER NOT NULL,
                                          applied_at TEXT DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO _schema_version(version) VALUES (2);
            CREATE TABLE clients (
                slug TEXT PRIMARY KEY, display_name TEXT NOT NULL, primary_domain TEXT NOT NULL,
                wp_base_url TEXT NOT NULL, wp_credentials_path TEXT NOT NULL, editor TEXT NOT NULL,
                default_category TEXT, default_tags TEXT NOT NULL DEFAULT '[]',
                title_template TEXT NOT NULL DEFAULT '{h1}',
                hubspot_company_id TEXT, brand_voice TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_updated TEXT DEFAULT CURRENT_TIMESTAMP, last_updated_by TEXT
            );
            INSERT INTO clients(slug, display_name, primary_domain, wp_base_url,
                                wp_credentials_path, editor, default_category,
                                hubspot_company_id, brand_voice)
            VALUES ('acme','Acme','acme.com','https://acme.com',
                    'data/secrets/acme.json','gutenberg','News','HS123','friendly');
            """
        )
        con.commit()
        con.close()

    def test_v3_drops_dead_columns_keeps_client(self) -> None:
        self._make_legacy_db()
        cfg = ClientStore(self.db).get("acme")  # opening triggers the migration
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.display_name, "Acme")
        self.assertEqual(cfg.default_category, "News")  # kept field survives

        con = sqlite3.connect(self.db)
        cols = {r[1] for r in con.execute("PRAGMA table_info(clients)")}
        version = con.execute(
            "SELECT MAX(version) FROM _schema_version"
        ).fetchone()[0]
        con.close()
        self.assertEqual(version, 3)
        self.assertNotIn("hubspot_company_id", cols)
        self.assertNotIn("brand_voice", cols)
        self.assertIn("editor", cols)  # a kept column is untouched


if __name__ == "__main__":
    unittest.main()
