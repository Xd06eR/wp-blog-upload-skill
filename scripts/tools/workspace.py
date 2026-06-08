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
  1. DOWNWARD search from $PWD: the nearest blog-upload-workspace/ in a
     sub-folder (breadth-first, shallowest wins). Skips hidden + heavy dirs
     (node_modules, .git, …) and is bounded by depth and a scanned-dir cap.
  2. UPWARD search: if nothing is below, walk $PWD's parents and take the first
     blog-upload-workspace/ sitting beside an ancestor (bounded by
     _MAX_WALKUP_DEPTH).
  3. BESIDE THE SKILL: the canonical home — `<skill>/../blog-upload-workspace`,
     i.e. a sibling of the skill folder (resolved from this file's location).
     Used if it already exists, and is also the CREATE target. This is what
     makes resolution location-independent: the skill always finds (or makes)
     its workspace next to itself, no matter where you launch, matching the
     documented siblings layout (`~/blog-upload` + `~/blog-upload-workspace`).

root() always returns a path (the beside-skill create target even when it does
not exist yet). find() returns only an EXISTING workspace, or None — read-only
CLI commands use it so that merely listing clients or the playbook index never
materialises a new (empty) workspace as a side effect.

There is no override flag and no environment variable.

Call ensure() at the top of WRITE entrypoints to guarantee the workspace
skeleton exists; read-only entrypoints resolve with find() and create nothing.
"""

from __future__ import annotations

from pathlib import Path

WORKSPACE_DIRNAME = "blog-upload-workspace"

# Downward-search bounds — keep discovery fast even in large trees.
_MAX_WALKDOWN_DEPTH = 8
_MAX_SCAN_DIRS = 4000
# Upward-search bound — how many parents of $PWD to check for a sibling
# workspace before giving up. Each check is one stat; 16 covers any realistic
# project nesting without statting to the filesystem root every call.
_MAX_WALKUP_DEPTH = 16
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


def _skill_root() -> Path:
    """The skill folder this code lives in.

    workspace.py sits at `<skill>/scripts/tools/workspace.py`, so the skill
    root is three parents up. Used to anchor the canonical workspace beside the
    skill regardless of the current working directory.
    """
    return Path(__file__).resolve().parents[2]


def _canonical_workspace() -> Path:
    """The workspace's canonical home: a sibling of the skill folder."""
    return _skill_root().parent / WORKSPACE_DIRNAME


def root() -> Path:
    """Resolve the workspace root. Does NOT create it.

    Order: downward search -> upward search -> beside the skill. See the module
    docstring. Always returns a path (the beside-skill create target even when
    it does not exist); use find() when you need 'an existing one, or None'.
    """
    cwd = Path.cwd()
    found = _find_workspace_downward(cwd) or _find_workspace_upward(cwd)
    if found is not None:
        return found
    return _canonical_workspace().resolve()


def find() -> Path | None:
    """Resolve an EXISTING workspace (downward, upward, then beside the skill),
    or None.

    Unlike root(), never returns a would-be create path. Read-only CLI commands
    use this so that listing clients or the playbook index never materialises a
    new (empty) workspace just by being run from the wrong directory — while
    still resolving the real beside-skill workspace from anywhere.
    """
    cwd = Path.cwd()
    found = _find_workspace_downward(cwd) or _find_workspace_upward(cwd)
    if found is not None:
        return found
    canonical = _canonical_workspace()
    return canonical if canonical.is_dir() else None


def _find_workspace_downward(start: Path) -> Path | None:
    """Breadth-first search of `start`'s sub-folders for a `blog-upload-workspace/`.

    Returns the SHALLOWEST match (nearest to `start`); ties broken
    alphabetically. Skips hidden + heavy build dirs and is bounded by
    `_MAX_WALKDOWN_DEPTH` and `_MAX_SCAN_DIRS`, so it stays fast in large trees
    and degrades to None (→ upward search / beside-skill) rather than hanging.
    Symlinked dirs are not followed (avoids cycles).
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


def _find_workspace_upward(start: Path) -> Path | None:
    """Walk up from `start`'s parents; return the first ancestor that has a
    `blog-upload-workspace/` child.

    This resolves the layout where the skill folder and the workspace are
    SIBLINGS: launched from inside the skill, the workspace is the parent's
    child, which downward search (sub-folders only) can never see. Bounded by
    `_MAX_WALKUP_DEPTH` so it does not stat its way to the filesystem root.
    Nearest ancestor wins; symlinked candidates are ignored.
    """
    for depth, ancestor in enumerate(start.resolve().parents):
        if depth >= _MAX_WALKUP_DEPTH:
            break
        candidate = ancestor / WORKSPACE_DIRNAME
        try:
            if candidate.is_dir() and not candidate.is_symlink():
                return candidate
        except OSError:
            continue  # unreadable ancestor — keep climbing
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
    """Create the workspace skeleton if missing. Idempotent. Returns root.

    Only WRITE entrypoints (init-workspace, onboard, upload) call this; when no
    workspace is found, root() points beside the skill, so a fresh workspace is
    created there. Read commands resolve with find() and never create.
    """
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
    """Explain how `root()` arrived at `resolved` (for operator visibility):
    'subfolder' (found below $PWD), 'parent' (found beside an ancestor via
    upward search), or 'canonical' (beside the skill — the create target)."""
    if resolved == _canonical_workspace().resolve():
        return "canonical"
    cwd = Path.cwd().resolve()
    try:
        resolved.relative_to(cwd)
        return "subfolder"
    except ValueError:
        return "parent"
