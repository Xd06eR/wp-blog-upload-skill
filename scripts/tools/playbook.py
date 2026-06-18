"""Per-client playbook — markdown notes the agent leaves for its future self.

After every SUCCESSFUL upload, the agent appends a 1-2 line lesson:
brief format quirks, brand voice gotchas, which adapter worked, etc.

Two access layers (progressive disclosure) — this is the key design point:

  - INDEX  build_index() returns ONE compact record per client: a curated
           `summary` plus brand `aliases`. Cheap enough to load on EVERY run
           (see the `playbook-index` CLI subcommand). It lets the agent resolve
           a brand the operator names ("ProKitchens") to the slug it actually
           uploads under ("foodwork") BEFORE the client is chosen. A per-slug
           body read cannot do this — you would need the slug to find the
           mapping that gives you the slug (chicken-and-egg). Hybrid summary:
           the curated frontmatter `summary` when present, else the newest
           lesson headline (so pre-frontmatter playbooks still say something).

  - BODY   read(slug) returns the full dated journal for ONE client — loaded
           lazily, only once the client is known.

Storage: data/playbooks/<slug>.md. Optional frontmatter at the very top carries
the always-loaded index fields; the rest is an append-only journal that rotates
oldest entries to <slug>.archive.md past MAX_LIVE_ENTRIES so context stays
bounded.

File shape:
    ---
    summary: ProKitchens (all langs) -> foodwork; one multilingual install.
    aliases: prokitchens
    ---
    # Playbook — <slug>

    ## YYYY-MM-DD — <one-line headline>

    <body markdown — 1-2 short paragraphs OR a bullet list>

Frontmatter is parsed with a tiny stdlib reader (no PyYAML — the skill is
pure-stdlib): `key: value` lines between two `---` fences; `aliases` is a
comma-separated list.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from . import workspace

MAX_LIVE_ENTRIES = 5

_ENTRY_HEADER = re.compile(r"^## \d{4}-\d{2}-\d{2}", re.MULTILINE)
_HEADLINE = re.compile(r"^## \d{4}-\d{2}-\d{2}\s*[—–-]\s*(.+?)\s*$", re.MULTILINE)
# Leading `---` fence block. `.match` anchors at string start, so a `---`
# horizontal rule later in the body is never mistaken for frontmatter.
_FRONTMATTER = re.compile(r"^---[ \t]*\n(.*?\n)?---[ \t]*\n", re.DOTALL)

_INDEX_FIELDS = ("summary", "aliases")


def _slug_path(slug: str, archive: bool = False) -> Path:
    pdir = workspace.playbooks_dir()
    pdir.mkdir(parents=True, exist_ok=True)
    suffix = ".archive.md" if archive else ".md"
    return pdir / f"{slug}{suffix}"


# --- frontmatter: the always-loaded index fields ----------------------------

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a leading `---` frontmatter block from the body.

    Returns (meta, body). `meta['aliases']` is a list[str]; other keys are
    plain strings. No frontmatter -> ({}, text) unchanged.
    """
    # Normalize CRLF/CR so a Windows-edited playbook still matches the `\n`
    # fence regex -- otherwise the frontmatter is missed and the always-loaded
    # index silently loses its curated summary + aliases.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text
    body = text[m.end():]
    raw = m.group(1) or ""
    meta: dict = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        key = key.strip().lower()
        val = val.strip()
        if key == "aliases":
            val = val.strip("[]")
            meta[key] = [a.strip().strip("'\"") for a in val.split(",") if a.strip()]
        else:
            meta[key] = val
    return meta, body


def _serialize_frontmatter(meta: dict) -> str:
    """Render meta back to a `---` block. Empty meta -> empty string.

    `summary` then `aliases` are emitted first for a stable, readable order.
    """
    items: list[str] = []
    if meta.get("summary"):
        items.append(f"summary: {meta['summary']}")
    if meta.get("aliases"):
        items.append(f"aliases: {', '.join(meta['aliases'])}")
    for key, val in meta.items():
        if key in _INDEX_FIELDS:
            continue
        items.append(f"{key}: {val}")
    if not items:
        return ""
    return "---\n" + "\n".join(items) + "\n---\n"


def _merge_aliases(existing: list[str], new: list[str]) -> list[str]:
    """Append new aliases, case-insensitively de-duplicated, order preserved."""
    merged = list(existing)
    seen = {a.lower() for a in merged}
    for a in new:
        a = a.strip()
        if a and a.lower() not in seen:
            merged.append(a)
            seen.add(a.lower())
    return merged


def _latest_headline(body: str) -> str:
    """Newest dated headline (entries are newest-last), or empty string."""
    heads = _HEADLINE.findall(body)
    return heads[-1].strip() if heads else ""


def _default_header(slug: str) -> str:
    return (
        f"# Playbook — {slug}\n\n"
        f"Notes the agent left for its future self. Newest at the bottom.\n\n"
    )


# --- read paths -------------------------------------------------------------

def read(slug: str) -> str:
    """Return the full live playbook (frontmatter + journal), or empty string."""
    path = _slug_path(slug)
    return path.read_text() if path.exists() else ""


def build_index() -> list[dict]:
    """One compact record per live playbook, cheap to load on EVERY run.

    Each record: {slug, summary, aliases, source}. Hybrid summary — curated
    frontmatter `summary` when set, else the newest lesson headline (so the
    pre-frontmatter playbooks still surface something). `source` flags which
    was used: 'summary' | 'headline' | 'empty'.
    """
    pdir = workspace.playbooks_dir()
    if not pdir.exists():
        return []
    index: list[dict] = []
    for path in sorted(pdir.glob("*.md")):
        if path.name.endswith(".archive.md"):
            continue
        meta, body = _parse_frontmatter(path.read_text())
        summary = (meta.get("summary") or "").strip()
        source = "summary"
        if not summary:
            summary = _latest_headline(body)
            source = "headline" if summary else "empty"
        index.append({
            "slug": path.stem,
            "summary": summary,
            "aliases": meta.get("aliases", []),
            "source": source,
        })
    return index


# --- write paths ------------------------------------------------------------

def set_meta(
    slug: str,
    *,
    summary: str | None = None,
    aliases: list[str] | None = None,
    replace_aliases: bool = False,
) -> Path:
    """Update the always-loaded index fields WITHOUT appending a lesson.

    Use to curate an existing playbook's one-line index entry (e.g. backfill a
    brand->slug mapping onto the 5 legacy playbooks). Aliases merge by default;
    pass replace_aliases=True to overwrite.
    """
    path = _slug_path(slug)
    existing = path.read_text() if path.exists() else ""
    meta, body = _parse_frontmatter(existing)
    if summary is not None:
        meta["summary"] = summary.strip()
    if aliases is not None:
        meta["aliases"] = (
            [a.strip() for a in aliases if a.strip()] if replace_aliases
            else _merge_aliases(meta.get("aliases", []), aliases)
        )
    if not body.strip():
        body = _default_header(slug)
    path.write_text(_serialize_frontmatter(meta) + body)
    return path


def append_lesson(
    slug: str,
    headline: str,
    body: str,
    *,
    summary: str | None = None,
    aliases: list[str] | None = None,
) -> Path:
    """Append a dated entry, rotate older entries, optionally curate the index.

    Pass `summary` / `aliases` when the lesson establishes a headline-level
    fact worth loading on EVERY run (especially a brand->slug mapping): they
    update the frontmatter `build_index()` reads. The dated journal entry is
    written either way.
    """
    path = _slug_path(slug)
    today = datetime.now().strftime("%Y-%m-%d")
    headline_clean = headline.strip().splitlines()[0][:120] if headline else "Run completed"
    body_clean = body.strip() if body else "(no lesson recorded)"
    new_entry = f"## {today} — {headline_clean}\n\n{body_clean}\n"

    existing = path.read_text() if path.exists() else ""
    meta, existing_body = _parse_frontmatter(existing)

    if summary is not None:
        meta["summary"] = summary.strip()
    if aliases is not None:
        meta["aliases"] = _merge_aliases(meta.get("aliases", []), aliases)

    if existing_body.strip():
        journal = existing_body.rstrip() + "\n\n" + new_entry
    else:
        journal = _default_header(slug) + new_entry

    journal = _rotate(slug, journal)
    path.write_text(_serialize_frontmatter(meta) + journal)
    return path


def _rotate(slug: str, content: str) -> str:
    """If the live journal has more than MAX_LIVE_ENTRIES entries, move the
    oldest ones to <slug>.archive.md and keep only the newest in the live file.
    Preserves the journal header (lines before the first ## entry). Operates on
    the journal body only — frontmatter is prepended by the caller, so it is
    never rotated away."""
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
