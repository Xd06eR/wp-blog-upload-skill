-- Blog Automation -- client store schema (SQLite)
--
-- Source of truth for the DB structure. client_store.py runs this DDL on
-- first init. Schema changes go here + a migration block in client_store._migrate().

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Schema version (incremented on each migration)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS _schema_version (
    version    INTEGER NOT NULL,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- ---------------------------------------------------------------------------
-- clients -- one row per client. Source of truth for all client context
-- consumed by every automation in the workspace.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS clients (
    -- Identity
    slug                    TEXT PRIMARY KEY,
    display_name            TEXT NOT NULL,
    primary_domain          TEXT NOT NULL,

    -- WordPress
    wp_base_url             TEXT NOT NULL,
    wp_credentials_path     TEXT NOT NULL,         -- absolute path to creds JSON (chmod 600)
    editor                  TEXT NOT NULL,         -- gutenberg | elementor | classic
    editor_version          TEXT,
    seo_plugin              TEXT NOT NULL DEFAULT 'none',  -- yoast | rankmath | aioseo | none
    default_category        TEXT,
    default_tags            TEXT NOT NULL DEFAULT '[]',    -- JSON array of strings
    title_template          TEXT NOT NULL DEFAULT '{h1}',

    -- Content / SEO context
    brand_voice             TEXT,
    locale                  TEXT NOT NULL DEFAULT 'en-US',
    forbidden_words         TEXT NOT NULL DEFAULT '[]',
    required_terms          TEXT NOT NULL DEFAULT '[]',
    internal_link_targets   TEXT NOT NULL DEFAULT '[]',

    -- Process
    primary_writers         TEXT NOT NULL DEFAULT '[]',
    approval_workflow       TEXT,
    blog_frequency          TEXT,

    -- Cross-system integrations
    slack_channel           TEXT,
    hubspot_company_id      TEXT,
    ahrefs_project_id       TEXT,
    gdrive_folder_id        TEXT,

    -- Metadata
    created_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated            TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_by         TEXT
);

CREATE INDEX IF NOT EXISTS idx_clients_editor ON clients(editor);
CREATE INDEX IF NOT EXISTS idx_clients_primary_domain ON clients(primary_domain);


-- ---------------------------------------------------------------------------
-- client_history -- audit log of changes to the clients table.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS client_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    slug            TEXT NOT NULL,
    changed_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    changed_by      TEXT,
    field           TEXT NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    FOREIGN KEY (slug) REFERENCES clients(slug) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_client_history_slug ON client_history(slug);
CREATE INDEX IF NOT EXISTS idx_client_history_changed_at ON client_history(changed_at);
