"""First-time client onboarding.

Tests credentials against WP, auto-detects editor type from existing posts,
and writes the credentials to data/secrets/<slug>.json + a row into the
clients table. Called by the agent (via onboard_new_client) when a writer
references a client we've never seen before.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, parse, request
from urllib.parse import urlparse

from . import workspace
from .client_store import get_store
from .wp_client import WPClient, WPCredentials, WPError, _normalize_site_root


@dataclass
class OnboardResult:
    slug: str
    detected_editor: str
    credentials_path: str
    site_name: str = ""


def derive_slug(site_url: str) -> str:
    """example.com -> example; client.wpenginepowered.com -> client."""
    host = urlparse(site_url if "://" in site_url else "https://" + site_url).hostname or ""
    head = host.split(".")[0] if host else "client"
    return re.sub(r"[^a-z0-9]+", "-", head.lower()).strip("-") or "client"


def derive_display_name(site_url: str) -> str:
    """Best-effort display name from URL until the team fills in the real one."""
    host = urlparse(site_url if "://" in site_url else "https://" + site_url).hostname or "Client"
    return host.replace("www.", "")


def client_exists(slug: str) -> bool:
    return get_store().exists(slug)


def register_client(
    slug: str,
    site_url: str,
    username: str,
    app_password: str,
    *,
    editor: str | None = None,
    title_template: str = "{h1}",
    default_category: str | None = None,
    default_tags: list[str] | None = None,
    display_name: str | None = None,
    by: str = "agent",
) -> OnboardResult:
    """Test credentials, detect editor if not given, write secret + DB row.

    Raises WPError on credential failure or unreachable site.
    """
    # Normalize once at the entry point so every downstream artifact (creds
    # JSON, DB row, editor probe, REST calls) shares the same clean site root.
    site_url = _normalize_site_root(site_url)
    creds = WPCredentials(site_url=site_url, username=username, app_password=app_password)
    site_name = _verify_login(creds)

    if not editor:
        editor = detect_editor(creds)

    workspace.ensure()
    secrets = workspace.secrets_dir()
    creds_path = secrets / f"{slug}.json"
    creds_payload = {
        "site_url": site_url,
        "username": username,
        "app_password": app_password,
    }
    creds_path.write_text(json.dumps(creds_payload, indent=2))
    creds_path.chmod(0o600)

    from .client_config import ClientConfig
    cfg = ClientConfig(
        slug=slug,
        display_name=display_name or site_name or derive_display_name(site_url),
        primary_domain=urlparse(_site_root(site_url)).hostname or slug,
        wp_base_url=_site_root(site_url),
        wp_credentials_path=str(creds_path),
        editor=editor,
        title_template=title_template,
        default_category=default_category,
        default_tags=default_tags or [],
    )
    get_store().save(cfg, by=by)

    return OnboardResult(
        slug=slug,
        detected_editor=editor,
        credentials_path=str(creds_path),
        site_name=site_name,
    )


def _wp_get(creds: WPCredentials, path: str, query: dict | None = None, timeout: int = 20) -> tuple[int, bytes]:
    url = creds.api_root + path
    if query:
        url = url + "&" + parse.urlencode(query)
    req = request.Request(url, method="GET", headers={
        "Authorization": creds.basic_auth_header(),
        "User-Agent": "BlogUpload-Agent/1.0",
    })
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except error.HTTPError as e:
        body = e.read() if hasattr(e, "read") else b""
        return e.code, body
    except error.URLError as e:
        raise WPError(f"Could not reach {creds.site_url}: {e.reason}") from e


def _verify_login(creds: WPCredentials) -> str:
    """GET /users/me with Basic auth — confirms credentials work."""
    status, body = _wp_get(creds, "users/me")
    if status == 401:
        raise WPError(
            "WordPress rejected the username + application password. "
            "Double-check the password (it has spaces) and that the user has Editor or Administrator role."
        )
    if status >= 400:
        raise WPError(f"WordPress login check failed (HTTP {status}): {body[:200]!r}")
    me = json.loads(body.decode("utf-8")) if body else {}
    return me.get("name") or me.get("slug") or creds.username


def detect_editor(creds: WPCredentials) -> str:
    """Fetch a recent post and infer editor from its content shape.

    Heuristics (in order):
      - content contains '<!-- wp:'   -> gutenberg
      - meta has '_elementor_data'    -> elementor
      - else                          -> classic
    """
    try:
        status, body = _wp_get(
            creds, "posts",
            query={"per_page": "5", "status": "publish,draft", "context": "edit"},
        )
    except WPError:
        return "gutenberg"

    if status >= 400 or not body:
        return "gutenberg"

    try:
        posts = json.loads(body.decode("utf-8")) or []
    except json.JSONDecodeError:
        return "gutenberg"

    for post in posts:
        content = (post.get("content") or {}).get("raw") or (post.get("content") or {}).get("rendered") or ""
        if "<!-- wp:" in content:
            return "gutenberg"
        meta = post.get("meta") or {}
        if "_elementor_data" in meta or post.get("elementor_data"):
            return "elementor"
    return "classic" if posts else "gutenberg"


def _site_root(site_url: str) -> str:
    """Single source of truth for URL normalization is wp_client.

    Kept as a thin wrapper so existing call sites in this module don't
    need to know about the helper move.
    """
    return _normalize_site_root(site_url)
