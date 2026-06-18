"""SQLite-backed client store.

Single source of truth for every client's context -- used by every automation
in this workspace. The store handles:

  - Reading + writing client config (clients table)
  - Audit log of every change (client_history table)

Schema lives in scripts/schema.sql (this package). Code never builds raw SQL
outside this module — callers go through the typed API.

Usage:
    from scripts.tools.client_store import get_store

    if not get_store().exists("example-client"):
        get_store().save(ClientConfig(slug="example-client", ...), by="agent")

    cfg = get_store().get("example-client")
    get_store().update_field("example-client", "brand_voice", "...", by="editor")
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


from . import workspace

# Schema lives inside the package (immutable, ships with code).
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"
_SCHEMA_VERSION = 2

_JSON_FIELDS = {
    "default_tags", "forbidden_words", "required_terms",
    "internal_link_targets", "primary_writers",
}


class ClientStoreError(Exception):
    """Raised on store operations that fail (missing client, schema issues, etc.)."""


class ClientStore:
    """Thread-safe SQLite wrapper. One instance per process is normal."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            workspace.ensure()
            db_path = workspace.db_path()
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self._init_schema()

    # ---------- schema management ----------------------------------------

    def _init_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        if not SCHEMA_PATH.exists():
            raise ClientStoreError(
                f"Schema file not found: {SCHEMA_PATH}. "
                f"This file is required to initialize the client store."
            )

        with self._connect() as con:
            con.executescript(SCHEMA_PATH.read_text())
            # Order by version, not applied_at: the timestamp has 1-second
            # resolution, so two migrations applied in the same second could
            # otherwise resolve in the wrong order.
            row = con.execute(
                "SELECT version FROM _schema_version ORDER BY version DESC LIMIT 1"
            ).fetchone()
            current = row["version"] if row else 0
            self._migrate(con, current)

    def _migrate(self, con: sqlite3.Connection, current: int) -> None:
        """Run incremental migrations from `current` to `_SCHEMA_VERSION`.

        For schema version N, add an `if current < N: ...` block here.
        """
        if current >= _SCHEMA_VERSION:
            return

        if current < 2:
            # Credential paths are now stored RELATIVE to the workspace root and
            # resolved to absolute at load time, so moving or renaming the
            # workspace no longer breaks credential lookup. Normalize any legacy
            # absolute paths to the canonical relative form.
            con.execute(
                "UPDATE clients SET wp_credentials_path = 'data/secrets/' || slug || '.json'"
            )

        con.execute(
            "INSERT INTO _schema_version(version) VALUES (?)", (_SCHEMA_VERSION,)
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            con = sqlite3.connect(self.db_path, isolation_level=None)  # autocommit
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys = ON")
            try:
                yield con
            finally:
                con.close()

    # ---------- read API --------------------------------------------------

    def exists(self, slug: str) -> bool:
        with self._connect() as con:
            row = con.execute("SELECT 1 FROM clients WHERE slug = ?", (slug,)).fetchone()
            return row is not None

    def get(self, slug: str) -> "ClientConfig | None":
        with self._connect() as con:
            row = con.execute("SELECT * FROM clients WHERE slug = ?", (slug,)).fetchone()
            if not row:
                return None
            return _row_to_config(row, self.db_path.parent / "secrets")

    def list_clients(self) -> list[str]:
        with self._connect() as con:
            return [r["slug"] for r in con.execute("SELECT slug FROM clients ORDER BY slug")]

    def all(self) -> list["ClientConfig"]:
        with self._connect() as con:
            secrets = self.db_path.parent / "secrets"
            return [_row_to_config(r, secrets) for r in con.execute("SELECT * FROM clients ORDER BY slug")]

    def history(self, slug: str, limit: int = 50) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM client_history WHERE slug = ? ORDER BY changed_at DESC LIMIT ?",
                (slug, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------- write API -------------------------------------------------

    def save(self, cfg: "ClientConfig", *, by: str = "agent") -> None:
        """Insert or update a client. Records each changed field in client_history."""
        existing = self.get(cfg.slug)
        payload = _config_to_row(cfg)
        payload["last_updated"] = _now_iso()
        payload["last_updated_by"] = by
        # On fresh insert, the dataclass's created_at is typically None — set it explicitly.
        if not existing or not payload.get("created_at"):
            payload["created_at"] = _now_iso()

        with self._connect() as con:
            cols = list(payload.keys())
            placeholders = ", ".join(["?"] * len(cols))
            assignments = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "slug")
            con.execute(
                f"INSERT INTO clients ({', '.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT(slug) DO UPDATE SET {assignments}",
                tuple(payload[c] for c in cols),
            )

            existing_payload = _config_to_row(existing) if existing else {}
            for field, new_value in payload.items():
                if field in {"last_updated", "last_updated_by", "created_at"}:
                    continue
                old_value = existing_payload.get(field)
                if str(old_value) != str(new_value):
                    con.execute(
                        "INSERT INTO client_history(slug, changed_by, field, old_value, new_value) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (cfg.slug, by, field, _stringify(old_value), _stringify(new_value)),
                    )

    def update_field(self, slug: str, field: str, value: Any, *, by: str = "agent") -> None:
        """Update a single field. Records the change in client_history.

        For JSON-array fields, pass a list — it's auto-encoded.
        """
        cfg = self.get(slug)
        if not cfg:
            raise ClientStoreError(f"No client with slug '{slug}'")

        if field in _JSON_FIELDS and not isinstance(value, str):
            stored_value = json.dumps(value)
        else:
            stored_value = value

        with self._connect() as con:
            row = con.execute(f"SELECT {field} FROM clients WHERE slug = ?", (slug,)).fetchone()
            if not row:
                raise ClientStoreError(f"No client with slug '{slug}'")
            old_value = row[field]
            con.execute(
                f"UPDATE clients SET {field} = ?, last_updated = ?, last_updated_by = ? WHERE slug = ?",
                (stored_value, _now_iso(), by, slug),
            )
            if str(old_value) != str(stored_value):
                con.execute(
                    "INSERT INTO client_history(slug, changed_by, field, old_value, new_value) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (slug, by, field, _stringify(old_value), _stringify(stored_value)),
                )

    def delete(self, slug: str, *, by: str = "agent") -> None:
        """Hard delete. Cascades to client_history."""
        with self._connect() as con:
            con.execute(
                "INSERT INTO client_history(slug, changed_by, field, old_value, new_value) "
                "VALUES (?, ?, ?, ?, ?)",
                (slug, by, "_DELETED", "active", "deleted"),
            )
            con.execute("DELETE FROM clients WHERE slug = ?", (slug,))


# ---------- module-level singleton ----------------------------------------

_store: "ClientStore | None" = None


def get_store(db_path: str | Path | None = None) -> ClientStore:
    """Module-level accessor. Tests can override db_path; production code uses the default."""
    global _store
    target = Path(db_path).expanduser().resolve() if db_path else workspace.db_path()
    if _store is None or target != _store.db_path:
        _store = ClientStore(target)
    return _store


# ---------- helpers --------------------------------------------------------

def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


def _row_to_config(row: sqlite3.Row, secrets_dir: Path) -> "ClientConfig":
    """Build a ClientConfig from a DB row, decoding JSON fields back to Python lists.

    The credential path is DERIVED from `secrets_dir` (which sits next to the
    clients.db) + the slug, ignoring whatever string is stored. This keeps
    credential lookup correct even after the workspace is moved or renamed.
    """
    from .client_config import ClientConfig
    data = dict(row)
    for f in _JSON_FIELDS:
        raw = data.get(f) or "[]"
        try:
            data[f] = json.loads(raw)
        except json.JSONDecodeError:
            data[f] = []
    data["wp_credentials_path"] = str(secrets_dir / f"{data['slug']}.json")
    return ClientConfig(**{k: v for k, v in data.items() if k in ClientConfig.__dataclass_fields__})


def _config_to_row(cfg: "ClientConfig") -> dict:
    """Serialize a ClientConfig to a dict suitable for SQLite INSERT/UPDATE.

    All ClientConfig fields are written; the DB enforces NOT NULL and applies
    defaults declared in schema.sql. We don't filter Nones here — that would
    silently drop intentional NULL writes (e.g. clearing a brand_voice).
    """
    data = asdict(cfg)
    for f in _JSON_FIELDS:
        data[f] = json.dumps(data.get(f) or [])
    # Store the credential path RELATIVE to the workspace root (canonical
    # data/secrets/<slug>.json). Resolved back to absolute on load, so moving
    # or renaming the workspace never breaks credential lookup.
    data["wp_credentials_path"] = f"data/secrets/{cfg.slug}.json"
    return data
