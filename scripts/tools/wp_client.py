"""Thin WordPress REST API wrapper — pure stdlib (urllib).

Reuses the wp_credentials.json pattern. Auth is HTTP Basic with WP
application password (username + app password).

Stays dependency-free so the skill folder is drop-in: no pip install
required.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, parse, request


class WPError(Exception):
    """Raised on non-2xx responses with a human-readable message."""


# Known WP admin suffixes — stripped to get the public site root.
# Order matters: longer suffixes first so `/wp-admin` is preferred over `/admin`.
_ADMIN_SUFFIXES = (
    "/wp-login.php",
    "/wp-admin",
    "/admin",
)


def _normalize_site_root(site_url: str) -> str:
    """Return the public site root from a user-supplied URL.

    Tolerates the common URL shapes operators paste:
      - https://client.com
      - https://client.com/
      - https://client.com/wp-admin
      - https://client.com/wp-admin/
      - https://client.com/wp-login.php
      - https://client.com/admin            (WP-Engine staging pattern)
      - https://client.com/admin/

    Strips any of the known admin suffixes and trailing slashes. Does not
    touch sub-directory installs (e.g. https://client.com/blog) since
    those aren't admin paths.
    """
    base = site_url.rstrip("/")
    for suffix in _ADMIN_SUFFIXES:
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return base.rstrip("/")


@dataclass
class WPCredentials:
    site_url: str
    username: str
    app_password: str

    @classmethod
    def load(cls, path: str | Path) -> "WPCredentials":
        data = json.loads(Path(path).read_text())
        return cls(
            site_url=data["site_url"],
            username=data["username"],
            app_password=data["app_password"],
        )

    @property
    def api_root(self) -> str:
        """Normalize site_url to site root, append REST route."""
        return _normalize_site_root(self.site_url) + "/?rest_route=/wp/v2/"

    @property
    def site_base(self) -> str:
        return _normalize_site_root(self.site_url)

    def basic_auth_header(self) -> str:
        token = f"{self.username}:{self.app_password}".encode()
        return "Basic " + base64.b64encode(token).decode()


class WPClient:
    """One client per WordPress site. Handles media + posts."""

    def __init__(self, creds: WPCredentials, timeout: int = 30):
        self.creds = creds
        self.timeout = timeout

    def upload_media(self, image_path: str | Path, alt_text: str = "") -> dict[str, Any]:
        path = Path(image_path)
        if not path.exists():
            raise WPError(f"Image not found: {path}")

        mime, _ = mimetypes.guess_type(path.name)
        mime = mime or "application/octet-stream"

        media = self._request(
            "POST", "media",
            body=path.read_bytes(),
            headers={
                "Content-Disposition": f'attachment; filename="{path.name}"',
                "Content-Type": mime,
            },
            action=f"upload media '{path.name}'",
        )

        if alt_text:
            self.update_media(media["id"], {"alt_text": alt_text})
            media["alt_text"] = alt_text
        return media

    def update_media(self, media_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST", f"media/{media_id}", json_body=fields,
            action=f"update media {media_id}",
        )

    def create_post(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = {**payload}
        payload.setdefault("status", "draft")
        return self._request(
            "POST", "posts", json_body=payload, action="create post",
        )

    def delete_post(self, post_id: int, force: bool = True) -> dict[str, Any]:
        return self._request(
            "DELETE", f"posts/{post_id}", query={"force": str(force).lower()},
            action=f"delete post {post_id}",
        )

    def delete_media(self, media_id: int, force: bool = True) -> dict[str, Any]:
        return self._request(
            "DELETE", f"media/{media_id}", query={"force": str(force).lower()},
            action=f"delete media {media_id}",
        )

    def find_category_id(self, slug: str) -> int | None:
        results = self._request(
            "GET", "categories", query={"slug": slug},
            action=f"lookup category '{slug}'",
        )
        return results[0]["id"] if results else None

    def find_or_create_tag(self, name: str) -> int:
        results = self._request(
            "GET", "tags", query={"search": name},
            action=f"lookup tag '{name}'",
        )
        for t in results:
            if t.get("name", "").lower() == name.lower():
                return t["id"]
        created = self._request(
            "POST", "tags", json_body={"name": name},
            action=f"create tag '{name}'",
        )
        return created["id"]

    # --- internals --------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        json_body: Any = None,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        action: str = "request",
    ) -> Any:
        # api_root already ends with '?rest_route=/wp/v2/' — extra params join with '&'.
        url = self.creds.api_root + path
        if query:
            url = url + "&" + parse.urlencode(query)

        req_headers = {
            "Authorization": self.creds.basic_auth_header(),
            "User-Agent": "BlogUpload-Agent/1.0",
        }
        if headers:
            req_headers.update(headers)

        data: bytes | None = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        elif body is not None:
            data = body

        req = request.Request(url, data=data, method=method, headers=req_headers)
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                if resp.status == 204 or not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
        except error.HTTPError as e:
            raw = e.read() if hasattr(e, "read") else b""
            try:
                payload = json.loads(raw.decode("utf-8"))
                msg = payload.get("message") or raw.decode("utf-8", errors="replace")[:300]
            except Exception:
                msg = raw.decode("utf-8", errors="replace")[:300]
            raise WPError(
                f"WordPress refused to {action} (HTTP {e.code}): {msg}"
            ) from e
        except error.URLError as e:
            raise WPError(f"Could not reach WordPress to {action}: {e.reason}") from e
