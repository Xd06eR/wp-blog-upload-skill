"""ClientConfig dataclass — mirrors the `clients` table in data/schema.sql.

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
    editor_version: str | None = None
    seo_plugin: str = "none"
    default_category: str | None = None
    default_tags: list[str] = field(default_factory=list)
    title_template: str = "{h1}"

    # Content / SEO context (informational; agent reads via get_client_context)
    brand_voice: str | None = None
    locale: str = "en-US"
    forbidden_words: list[str] = field(default_factory=list)
    required_terms: list[str] = field(default_factory=list)
    internal_link_targets: list[str] = field(default_factory=list)

    # Process
    primary_writers: list[str] = field(default_factory=list)
    approval_workflow: str | None = None
    blog_frequency: str | None = None

    # Cross-system integrations
    slack_channel: str | None = None
    hubspot_company_id: str | None = None
    ahrefs_project_id: str | None = None
    gdrive_folder_id: str | None = None

    # Metadata (populated by the store)
    created_at: str | None = None
    last_updated: str | None = None
    last_updated_by: str | None = None
