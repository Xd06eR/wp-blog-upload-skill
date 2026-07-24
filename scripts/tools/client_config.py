"""ClientConfig dataclass — mirrors the `clients` table in scripts/schema.sql.

Lives in its own module so client_store.py can import it without pulling in
the markdown parser (`parse_md`, which upload_blog.py uses but client_store doesn't need).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ClientConfig:
    """One row in the clients table. Loaded via client_store.get(slug)."""
    # Identity
    slug: str
    display_name: str
    primary_domain: str

    # WordPress
    wp_base_url: str
    wp_credentials_path: str
    editor: str
    default_category: str | None = None
    default_tags: list[str] = field(default_factory=list)
    title_template: str = "{h1}"

    # Metadata (populated by the store)
    created_at: str | None = None
    last_updated: str | None = None
    last_updated_by: str | None = None
