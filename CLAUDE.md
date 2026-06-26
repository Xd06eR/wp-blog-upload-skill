# Blog Upload Skill — Developer Context

This file is for **whoever maintains or extends this skill** (human or agent). It captures the *why* behind the design so the context survives a `git clone` into a fresh machine. It is not needed to *run* the skill.

Doc map:

| File | Audience | Purpose |
|---|---|---|
| `CLAUDE.md` (this file) | Maintainer / agent | Design rationale, conventions, how to extend |
| `SKILL.md` | Agent | Operational workflow the agent follows at runtime |
| `REFERENCE.md` | Agent | Full SOP, CLI reference, failure recovery |
| `README.md` | Developer | Project overview + install |
| `GUIDE.md` / `GUIDE.html` | Non-technical users | Step-by-step usage |

If you are **running** the skill, read `SKILL.md`. If you are **evolving** it, read this file first.

> **Agent-agnostic.** This skill works with any AI coding agent that can run a shell — Claude Code, GitHub Copilot, Codex, Kimi Code, Antigravity, opencode, and others. The portable core is the Python CLI; each agent just invokes it its own way. This file is also published as `AGENTS.md` (a symlink to `CLAUDE.md`) so agents that look for that name pick up the same context.

## What this skill is

An agent parses a blog brief (`.docx` or `.md`, auto-detected by extension), picks the right client from a local SQLite registry, renders the body for that client's WordPress editor (Gutenberg / Classic / Elementor), and `POST`s it to WP REST as `status=draft`. No preview, no approval gate — the writer reviews in WP admin (where Yoast / RankMath meta must be filled by hand anyway, since those plugins have no REST support). Images supplied alongside the brief (a `--media-dir` folder, or inline `image` blocks in an `upload-prepared` payload) are uploaded to the WP media library, appended to the body, and the first is set as the featured image.

## Design philosophy (and why)

- **Local agent skill + Python stdlib CLI** (works with any agent that runs a shell — Claude Code, GitHub Copilot, Codex, Kimi Code, Antigravity, opencode). No server, no `pip install`, zero infrastructure to maintain.
- **Pure stdlib only** (`urllib`, `sqlite3`, `re`, `dataclasses`, plus `zipfile` + `xml.etree` for the `.docx` reader). Adding a dependency means non-technical colleagues can't install by copy/clone.
- **Draft-only, hardcoded.** The CLI always sends `status=draft`; it refuses to publish. The draft never goes public until a human edits it in WP admin, which is also where SEO meta gets filled — so the content review happens there, not in chat. That is why there is no preview/approval step.
- **Immutable skill folder, mutable workspace.** Skill code + docs stay portable (`cp -r` / `git clone`); all per-user state (DB, secrets, playbooks, briefs) lives in a separate `blog-upload-workspace/` outside the skill.

## Architecture

```text
blog-upload/                     ← this repo == the installable skill (root)
├── SKILL.md                     ← agent workflow (runtime)
├── REFERENCE.md                 ← full agent SOP
├── README.md                    ← project overview
├── GUIDE.md / GUIDE.html        ← non-technical user guide
├── CLAUDE.md                    ← maintainer context (AGENTS.md symlinks here)
├── scripts/                     ← pure-stdlib Python package
│   ├── run.py                   ← CLI entrypoint (argparse dispatch)
│   ├── upload_blog.py           ← orchestrator: parse → render → POST
│   ├── schema.sql               ← SQLite DDL (clients + client_history)
│   ├── adapters/                ← gutenberg | classic | elementor | _escape
│   └── tools/                   ← intake, parse_md, docx_reader, parse_docx,
│                                  wp_client, workspace, client_store,
│                                  client_config, onboarding, playbook
└── tests/                       ← stdlib unittest

blog-upload-workspace/           ← per-user state, NOT in this repo (gitignored)
├── data/{clients.db, secrets/<slug>.json, playbooks/<slug>.md}
└── briefs/upload/<name>.{docx,md}
```

Data flow:

```text
brief (.docx | .md) → intake.parser_for() → parse_docx | parse_md → render (adapter) → WP REST /posts (draft)
```

`.docx` parses natively for recognized layouts. A brief that drifts — a `.md`
off-schema, or a `.docx` whose layout isn't recognized — falls back to agent
mapping (markdown: `inspect-brief` → normalize or `ParsedDoc` JSON; docx:
`docx_reader` dump → `ParsedDoc` JSON) — see "Brief format + fallback".

## Key components

- **`tools/intake.py`** — format dispatch: `parser_for(path)` picks `parse_docx` (`.docx`) or `parse_md` (else). Both share one `parse` / `list_briefs` surface and the same `ParsedDoc`, so render + upload stay format-agnostic.
- **`tools/docx_reader.py`** — pure-stdlib WordprocessingML reader (`zipfile` + `xml.etree`); exposes paragraphs/tables (nesting preserved), bold/style/list-item detection, and resolved hyperlinks. Forbids DOCTYPE (billion-laughs guard — no `defusedxml` under no-pip).
- **`tools/parse_docx.py`** — `.docx` → `ParsedDoc`, mirroring `parse_md`'s API. Exists because some briefs wrap the body in a table cell that markdown export flattens; reading the `.docx` keeps the structure. Covers the house template, multi-body translation files, and paragraph-stream multi-brief; fail-loud on empty body / missing H1.
- **`tools/parse_md.py`** — strict markdown parser + `inspect()` debug dump. Single- and multi-client briefs (`### **Brand**` sections); strips markdown backslash-escapes (see "Markdown escaping"). Owns the shared helpers `parse_docx` reuses (`_HEADING_LINE`, `clean_keywords`, `_convert_inline`) and the `Brief`/`Block`/`ParsedDoc` dataclasses (`Block.kind` includes `table`).
- **`tools/workspace.py`** — resolves the workspace root. Order: **downward search** (nearest `blog-upload-workspace/` in a sub-folder of `$PWD`; breadth-first, shallowest wins; skips hidden + heavy dirs; bounded) → **upward search** (first `blog-upload-workspace/` beside an ancestor of `$PWD`, bounded by `_MAX_WALKUP_DEPTH`; resolves the siblings layout when a command runs from inside the skill) → **beside the skill** (`<skill>/../blog-upload-workspace`, anchored via `__file__`): used if present, else the create target. `root()` always returns a path; `find()` returns an existing workspace or `None`, and read-only CLI commands use `find()` so they never create a phantom workspace. No override flag, no env var.
- **`adapters/`** — one renderer per editor (gutenberg / classic / elementor) + shared `_escape.py`. All demote body `<h1>` to `<h2>` and inject the hidden `<!-- TODO META FOR HUMAN -->` comment. `_escape` carries the cross-adapter rules: escape text spans but keep inline `<a>`/`<strong>`, neutralize `-->` in the meta comment, and `_escape_attr` for image `alt`/`src` attributes. Lists render as `wp:list-item`; `table` blocks as real `<table>`; `image` blocks as the editor's native image markup (`wp:image` / `<figure><img>`).
- **`tools/client_store.py` + `schema.sql`** — SQLite registry (`clients`, `client_history` with `ON DELETE CASCADE`).
- **`tools/onboarding.py`** — credentials flow: file → CLI → chmod-600 secrets file (the DB records only the path); the agent never sees a raw password. Refuses to silently overwrite a different client that derives the same slug (`--slug` disambiguates), and reports a defaulted vs detected editor honestly.
- **`tools/wp_client.py`** — thin WP REST client (`urllib`); `upload_media()` POSTs an image file to `/wp/v2/media`. `upload_blog._resolve_media()` calls it for each `image` block, fills `media_id`/`media_url`, and sets the first as the post's `featured_media`; `_media_dir_blocks()` turns a `--media-dir` folder into appended image blocks.
- **`tools/playbook.py`** — per-client agent memory (`playbooks/<slug>.md`). Two layers: an always-load **index** (`build_index()` → `playbook-index` CLI) of curated `summary` + brand `aliases` per client (frontmatter; hybrid-falls back to the newest headline), and the lazy full **body** (`read(slug)`). The index resolves brand→slug *before* client pick; `set_meta()`/`append_lesson(summary=, aliases=)` curate it.

## Invocation convention

```bash
PYTHONPATH=<skill-dir> python3 -B -m scripts.run <subcommand> ...
```

`<skill-dir>` = absolute path to this folder. **No environment variable or `~/.bashrc` setup needed** — your agent resolves the path from wherever the skill is installed (in Claude Code, via the `@blog-upload` tag). `-B` suppresses `__pycache__` so the folder stays clean for copy/clone.

## Brief format + fallback

`.docx` is the safer default: some writers wrap the article body in a table cell, which markdown export can flatten (structure lost). `parse_docx` reads such briefs natively, so a `.docx` rarely needs any fallback. The `.md` canonical schema: an `### **Brand**` section header, a pipe table with URL / H1 / Meta Title / Meta Description / Keywords / Word count, then body with `**H1:/H2:/H3:**` headings. Full schema in `REFERENCE.md`. Writer formats vary — the parser covers common shapes and the agent adapts to the rest.

The fallback fires when `list-briefs` returns `[]` (the deterministic parser found no section). For a `.md` with no `.docx` twin, the agent maps it with `inspect-brief` and either **normalizes it** (Route A, default — mechanical fixes only) or **emits a `ParsedDoc` JSON** for `upload-prepared` (Route B). A `.docx` whose layout `parse_docx` doesn't recognize returns `[]` too; since `inspect-brief` refuses `.docx`, the agent dumps its structure with `docx_reader` (a one-off `-c`) and takes **Route B**, emitting the `ParsedDoc` JSON from the reader's already-extracted HTML (in-body tables, links, and bold preserved). Both routes write to a **temp file outside the workspace and delete it after** — never leave a `*-normalized.md` / `_prepared_*.json` artifact in `briefs/upload/` or `data/` (it confuses the non-technical operator).

**Verbatim rule (non-negotiable):** body prose is copied word-for-word. The agent's job is structural mapping, never content rewriting. Only normalize heading levels, list markers, escape characters, and pipe-cell artifacts.

## Markdown escaping

Google Docs / Word markdown export over-escapes punctuation (`F\&B`, `1\.`, `co\-op`, `50\%`). `parse_md._unescape_md()` strips a backslash before any ASCII-punctuation character (the CommonMark rule), applied to **both** the title path (`_strip_inline_md`) and the body path (`_convert_inline`). In `_convert_inline` it runs *after* link/bold conversion so escaped structural characters (`\[`, `\*`) can't masquerade as markdown syntax. Regression test: `tests/test_parse_md.py`.

## Testing

```bash
PYTHONPATH=<skill-dir> python3 -B -m unittest discover -s tests -v
```

Pure-stdlib `unittest` (no pytest, no pip). Practice TDD: add a failing test that reproduces the issue first, then make it pass.

## Conventions

- **Many small files** (~200–400 lines, 800 max); organize by domain.
- **Immutable skill folder** — never write scratch scripts or runtime state into the skill; one-off code runs via `python3 -B -c "..."`.
- **Keep `GUIDE.md` and `GUIDE.html` in sync** — they are hand-authored (no markdown→HTML converter on the toolchain); edit both together.

## Out of scope (by design)

Content generation · image *generation* / editing / resizing (image **upload** is in scope) · internal-link injection · Yoast / RankMath meta via REST (unsupported by those plugins) · auto-publish · updating existing posts (this skill only creates new drafts).

## Hard rules (non-negotiable)

1. **Draft only** — never override `status=draft`.
2. **No credentials in chat** — onboarding is file → CLI → chmod-600 secrets file (the DB stores only the path).
3. **No pip** — pure stdlib.
4. **No scratch scripts on disk** — use `python3 -B -c`.
5. **Workspace is sacred** — never delete `clients.db` or `playbooks/` without explicit operator approval; they hold accumulated knowledge.
