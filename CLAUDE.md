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

An agent parses a markdown blog brief, picks the right client from a local SQLite registry, renders the body for that client's WordPress editor (Gutenberg / Classic / Elementor), and `POST`s it to WP REST as `status=draft`. No preview, no approval gate — the writer reviews in WP admin (where Yoast / RankMath meta must be filled by hand anyway, since those plugins have no REST support).

## Design philosophy (and why)

- **Local agent skill + Python stdlib CLI** (works with any agent that runs a shell — Claude Code, GitHub Copilot, Codex, Kimi Code, Antigravity, opencode). No server, no `pip install`, zero infrastructure to maintain.
- **Pure stdlib only** (`urllib`, `sqlite3`, `re`, `dataclasses`). Adding a dependency means non-technical colleagues can't install by copy/clone.
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
│   ├── adapters/                ← gutenberg | classic | elementor renderers
│   └── tools/                   ← parse_md, wp_client, workspace,
│                                  client_store, client_config, onboarding,
│                                  playbook
└── tests/                       ← stdlib unittest

blog-upload-workspace/           ← per-user state, NOT in this repo (gitignored)
├── data/{clients.db, secrets/<slug>.json, playbooks/<slug>.md}
└── briefs/upload/<name>.md
```

Data flow:

```text
.md brief → parse_md (strict parser) ──hit──→ render (adapter) → WP REST /posts (draft)
                     │
                     └──miss ([])──→ agent maps via inspect-brief →
                          Route A: normalize on disk → re-parse
                          Route B: emit ParsedDoc JSON → upload-prepared
```

## Key components

- **`tools/parse_md.py`** — strict markdown parser + `inspect()` debug dump. Handles single- and multi-client briefs (`### **Brand**` sections). Strips markdown backslash-escapes (see "Markdown escaping" below).
- **`tools/workspace.py`** — resolves the workspace root. Order: **downward search** for the nearest `blog-upload-workspace/` in a sub-folder of `$PWD` (breadth-first, shallowest wins; skips hidden + heavy dirs; bounded by depth + a scanned-dir cap) → otherwise created in the current directory (`$PWD/blog-upload-workspace`). No override flag, no env var.
- **`adapters/`** — one renderer per editor. All three demote body `<h1>` to `<h2>` (post title is already the page H1) and inject a hidden `<!-- TODO META FOR HUMAN -->` comment carrying the meta-title/description.
- **`tools/client_store.py` + `schema.sql`** — SQLite registry (`clients`, `client_history` with `ON DELETE CASCADE`).
- **`tools/onboarding.py`** — credentials flow: file → CLI → chmod-600 secrets file (the DB records only the path). The agent never sees a raw password.
- **`tools/wp_client.py`** — thin WP REST client (`urllib`).
- **`tools/playbook.py`** — per-client agent memory (`playbooks/<slug>.md`).

## Invocation convention

```bash
PYTHONPATH=<skill-dir> python3 -B -m scripts.run <subcommand> ...
```

`<skill-dir>` = absolute path to this folder. **No environment variable or `~/.bashrc` setup needed** — your agent resolves the path from wherever the skill is installed (in Claude Code, via the `@blog-upload` tag). `-B` suppresses `__pycache__` so the folder stays clean for copy/clone.

## Brief format + alien-format fallback

Canonical schema: an `### **Brand**` section header, a pipe table with URL / H1 / Meta Title / Meta Description / Keywords / Word count, then body with `**H1:/H2:/H3:**` headings. Full schema in `REFERENCE.md`.

When `list-briefs` returns `[]` the brief drifted from the schema. The agent then maps it with `inspect-brief` and either **normalizes it on disk** (Route A, default — mechanical fixes only) or **emits a `ParsedDoc` JSON** for `upload-prepared` (Route B, structurally alien briefs).

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

Content generation · image upload · internal-link injection · Yoast / RankMath meta via REST (unsupported by those plugins) · auto-publish · updating existing posts (this skill only creates new drafts).

## Hard rules (non-negotiable)

1. **Draft only** — never override `status=draft`.
2. **No credentials in chat** — onboarding is file → CLI → chmod-600 secrets file (the DB stores only the path).
3. **No pip** — pure stdlib.
4. **No scratch scripts on disk** — use `python3 -B -c`.
5. **Workspace is sacred** — never delete `clients.db` or `playbooks/` without explicit operator approval; they hold accumulated knowledge.
