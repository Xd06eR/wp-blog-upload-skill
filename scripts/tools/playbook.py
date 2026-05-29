"""Per-client playbook — markdown notes the agent leaves for its future self.

After every SUCCESSFUL upload, the agent appends a 1-2 line lesson:
brief format quirks, brand voice gotchas, which adapter worked, etc.
On the next run for the same client, the agent reads the playbook BEFORE
rendering and benefits from past discoveries instead of re-deriving them.

Storage: data/playbooks/<slug>.md (markdown, append-only). Rotates the
oldest entries to <slug>.archive.md when the live file holds more than
MAX_LIVE_ENTRIES so the agent's context stays bounded.

Schema (per entry):
    ## YYYY-MM-DD — <one-line headline>

    <body markdown — 1-2 short paragraphs OR a bullet list>

Two entries are separated by a blank line. Headlines are ISO dates so
the playbook reads as a chronological journal.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from . import workspace

MAX_LIVE_ENTRIES = 5

_ENTRY_HEADER = re.compile(r"^## \d{4}-\d{2}-\d{2}", re.MULTILINE)


def _slug_path(slug: str, archive: bool = False) -> Path:
    pdir = workspace.playbooks_dir()
    pdir.mkdir(parents=True, exist_ok=True)
    suffix = ".archive.md" if archive else ".md"
    return pdir / f"{slug}{suffix}"


def read(slug: str) -> str:
    """Return the live playbook contents for a client, or empty string."""
    path = _slug_path(slug)
    return path.read_text() if path.exists() else ""


def append_lesson(slug: str, headline: str, body: str) -> Path:
    """Append a dated entry and rotate older entries to the archive."""
    path = _slug_path(slug)
    today = datetime.now().strftime("%Y-%m-%d")
    headline_clean = headline.strip().splitlines()[0][:120] if headline else "Run completed"
    body_clean = body.strip() if body else "(no lesson recorded)"
    new_entry = f"## {today} — {headline_clean}\n\n{body_clean}\n"

    existing = path.read_text() if path.exists() else ""
    if existing.strip():
        combined = existing.rstrip() + "\n\n" + new_entry
    else:
        combined = (
            f"# Playbook — {slug}\n\n"
            f"Notes the agent left for its future self. Newest at the bottom.\n\n"
            f"{new_entry}"
        )

    combined = _rotate(slug, combined)
    path.write_text(combined)
    return path


def _rotate(slug: str, content: str) -> str:
    """If the live file has more than MAX_LIVE_ENTRIES entries, move the
    oldest ones to <slug>.archive.md and keep only the newest in the live
    file. Preserves the file header (lines before the first ## entry)."""
    matches = list(_ENTRY_HEADER.finditer(content))
    if len(matches) <= MAX_LIVE_ENTRIES:
        return content

    header = content[: matches[0].start()].rstrip()
    cutoff = matches[-MAX_LIVE_ENTRIES].start()
    archive_chunk = content[matches[0].start():cutoff].strip()
    live_chunk = content[cutoff:].strip()

    if archive_chunk:
        archive_path = _slug_path(slug, archive=True)
        prior_archive = (
            archive_path.read_text() if archive_path.exists()
            else f"# Playbook archive — {slug}\n\nOldest first.\n\n"
        )
        archive_path.write_text(prior_archive.rstrip() + "\n\n" + archive_chunk + "\n")

    return header + "\n\n" + live_chunk + "\n"
