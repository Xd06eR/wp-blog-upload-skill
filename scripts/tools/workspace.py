"""Workspace resolution + bootstrap.

A workspace holds the MUTABLE state of the blog-upload skill:
  - data/clients.db          per-workspace SQLite
  - data/secrets/<slug>.json  per-client WP credentials (chmod 600)
  - data/secrets/.env.example credentials template
  - data/playbooks/<slug>.md  agent's per-client memory
  - briefs/upload/<name>.md   operator drops markdown briefs here

The skill folder itself stays immutable (SKILL.md + scripts); this
separation makes the skill portable and the workspace local-per-user.

Resolution order:
  1. Downward search from $PWD: the nearest blog-upload-workspace/ in a
     sub-folder (breadth-first, shallowest wins). Skips hidden + heavy dirs
     (node_modules, .git, …) and is bounded by depth and a scanned-dir cap.
  2. $PWD/blog-upload-workspace  (created in the current directory if nothing
     is found below).

There is no override flag and no environment variable: the workspace is found
in a sub-folder of where you launch, or created in the current directory.

Call ensure() at the top of every CLI entrypoint to guarantee the
workspace skeleton exists before tools that need it (sqlite, secrets,
runs) run.
"""

from __future__ import annotations

from pathlib import Path

WORKSPACE_DIRNAME = "blog-upload-workspace"

# Downward-search bounds — keep discovery fast even in large trees.
_MAX_WALKDOWN_DEPTH = 8
_MAX_SCAN_DIRS = 4000
_SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", "target", ".next", ".cache", ".idea", ".vscode",
    "site-packages", ".tox", ".mypy_cache", ".pytest_cache",
})


_ENV_EXAMPLE_TEMPLATE = """{
  "site_url": "https://your-client-site.com",
  "username": "your.wp.username",
  "app_password": "xxxx xxxx xxxx xxxx xxxx xxxx"
}

// HOW TO USE
// 1. Copy this file to data/secrets/_pending.json
// 2. Edit _pending.json with real WP credentials for ONE client
// 3. The agent will read it, register the client, and delete the file.
//
// Generate the app_password at:
//   WP Admin -> Users -> Profile -> Application Passwords
//
// Never commit a real credentials file. Real WP creds belong only in
// data/secrets/<slug>.json (chmod 600, your-user-only).
"""


def root() -> Path:
    """Resolve the workspace root. Does NOT create it.

    Order: downward search of sub-folders -> create in the current directory
    ($PWD/blog-upload-workspace). See the module docstring.
    """
    found = _find_workspace_downward(Path.cwd())
    if found is not None:
        return found

    return (Path.cwd() / WORKSPACE_DIRNAME).resolve()


def _find_workspace_downward(start: Path) -> Path | None:
    """Breadth-first search of `start`'s sub-folders for a `blog-upload-workspace/`.

    Returns the SHALLOWEST match (nearest to `start`); ties broken
    alphabetically. Skips hidden + heavy build dirs and is bounded by
    `_MAX_WALKDOWN_DEPTH` and `_MAX_SCAN_DIRS`, so it stays fast in large trees
    and degrades to None (→ current-directory fallback) rather than hanging. Symlinked dirs
    are not followed (avoids cycles).
    """
    start = start.resolve()
    # Launched from inside the workspace folder itself? Use it.
    if start.name == WORKSPACE_DIRNAME and start.is_dir():
        return start

    queue: list[tuple[Path, int]] = [(start, 0)]
    scanned = 0
    while queue:
        current, depth = queue.pop(0)
        try:
            children = sorted(
                p for p in current.iterdir()
                if p.is_dir() and not p.is_symlink()
            )
        except OSError:
            continue  # unreadable directory — skip it
        # Shallowest-first: a match at this level wins before we descend.
        for child in children:
            if child.name == WORKSPACE_DIRNAME:
                return child
        if depth < _MAX_WALKDOWN_DEPTH:
            for child in children:
                if child.name in _SKIP_DIRS or child.name.startswith("."):
                    continue
                queue.append((child, depth + 1))
        scanned += 1
        if scanned >= _MAX_SCAN_DIRS:
            break
    return None


def data_dir() -> Path:
    return root() / "data"


def secrets_dir() -> Path:
    return root() / "data" / "secrets"


def playbooks_dir() -> Path:
    return root() / "data" / "playbooks"


def briefs_dir() -> Path:
    return root() / "briefs" / "upload"


def db_path() -> Path:
    return data_dir() / "clients.db"


def ensure() -> Path:
    """Create the workspace skeleton if missing. Idempotent. Returns root."""
    r = root()
    r.mkdir(parents=True, exist_ok=True)

    for d in (data_dir(), playbooks_dir(), briefs_dir()):
        d.mkdir(parents=True, exist_ok=True)

    sec = secrets_dir()
    sec.mkdir(parents=True, exist_ok=True)
    try:
        sec.chmod(0o700)
    except OSError:
        pass

    env_example = sec / ".env.example"
    if not env_example.exists():
        env_example.write_text(_ENV_EXAMPLE_TEMPLATE)

    return r


def describe() -> dict:
    """Plain dict for logs/agent reporting."""
    r = root()
    return {
        "root": str(r),
        "exists": r.exists(),
        "source": _resolution_source(r),
        "data_dir": str(data_dir()),
        "briefs_dir": str(briefs_dir()),
    }


def _resolution_source(resolved: Path) -> str:
    """Explain how `root()` arrived at `resolved` (for operator visibility)."""
    if resolved == (Path.cwd() / WORKSPACE_DIRNAME).resolve():
        return "cwd"
    return "subfolder"
