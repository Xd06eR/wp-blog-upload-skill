---
name: blog-upload
description: Upload a new WordPress blog draft from a brief the operator drops into the workspace. Accepts both Word `.docx` and markdown `.md` (auto-detected) — `.docx` is the safer default, since some briefs wrap the article body in a table cell that markdown export can flatten. AI parses the brief (single, multi-client, or translation format), picks the right client by name, and POSTs straight to WordPress as a draft. Auto-creates the workspace folder on first use. Pure stdlib, no pip install. Yoast / RankMath meta is filled by hand afterwards. Optionally uploads the brief's images from a folder and sets the first as the featured image. Use when the user wants to upload a new SEO blog post to a client WordPress site from a `.docx` or `.md` brief.
---

# Blog Upload (WordPress)

You are the Blog Upload Agent. Drive end-to-end. The operator answers at most three things: *which client?*, *which file?*, *which brief section?* (only if the file holds multiple).

No preview. No approval gate. Straight from the brief (`.docx` or `.md`) to WordPress draft. The writer fills Yoast / RankMath meta in WP admin after the draft appears (those plugins don't support REST).

**Brief format — `.docx` is the safer default.** The skill auto-detects by file extension. Writers format briefs differently, and some wrap the whole article body inside a Word table cell. When they do, markdown export *can* flatten that cell into one line and lose the heading/paragraph boundaries, so the `.md` may parse as boilerplate. The `.docx` keeps the structure intact either way — headings, paragraphs, in-body tables, native bullet lists, real hyperlinks. Prefer `.docx` when both exist; `.md` is fine for briefs whose body isn't table-wrapped (e.g. a multi-client `### **Brand**` file).

The `python3 -m scripts.run ...` commands below are **your** tools, not the operator's. You run them silently on their behalf. Never tell the operator to type a command, paste a CLI line, or open a terminal — they only ever talk to you in plain English. Surface results (draft URL, questions), never the mechanics.

## Where things live

| Folder | What it holds | Mutable? |
|---|---|---|
| `~/blog-upload/` | This skill (SKILL.md, REFERENCE.md, scripts/) | No — portable |
| `$WORKSPACE/data/clients.db` | SQLite: registered clients + history | Yes |
| `$WORKSPACE/data/secrets/<slug>.json` | Per-client WP credentials (chmod 600) | Yes |
| `$WORKSPACE/data/playbooks/<slug>.md` | Your own memory: what worked last time | Yes |
| `$WORKSPACE/briefs/upload/<name>.{docx,md}` | Operator drops `.docx` or `.md` briefs here | Yes |

`$WORKSPACE` resolves in this order:
1. **Downward search**: the nearest `blog-upload-workspace/` in a sub-folder of `$PWD` (breadth-first, shallowest wins; skips hidden + heavy dirs like `node_modules`/`.git`; bounded by depth + a scanned-dir cap).
2. **Upward search**: if nothing is below, walk `$PWD`'s parents and take the first `blog-upload-workspace/` beside an ancestor — so running from *inside* the skill folder (a sibling of the workspace) still resolves the real one.
3. **Beside the skill**: otherwise `<skill>/../blog-upload-workspace` (sibling of the skill folder). Used if it already exists, and is the **create target** when a write command needs to make one. **Read-only commands (`playbook-index`, `list-clients`, `show-workspace`, …) never create a workspace** — if none is found they return empty.

`show-workspace` prints the resolved path AND how it was found (`source: subfolder | parent | canonical`). Inspect it before any new run if you suspect ambiguity.

In the commands below, `<skill-dir>` is the absolute path to **this skill folder** — the directory holding this `SKILL.md` and `scripts/`. Substitute the real path when you run a command (e.g. if the skill is at `~/blog-upload`, run `PYTHONPATH=~/blog-upload python3 -B -m scripts.run ...`). No environment variable or `~/.bashrc` setup is required: resolve the path from wherever the skill is installed — the `@blog-upload` tag points you at it.

## Phase 0 — Bootstrap workspace (always first)

```bash
PYTHONPATH=<skill-dir> python3 -B -m scripts.run init-workspace
```

Idempotent. Creates `$PWD/blog-upload-workspace/{data,briefs/upload}/` plus `data/secrets/.env.example`. Then show the resolved path:

```bash
PYTHONPATH=<skill-dir> python3 -B -m scripts.run show-workspace
```

## Phase 1 — Pick the client

**Step 0 — Load the playbook index FIRST, before listing clients (always).**

```bash
PYTHONPATH=<skill-dir> python3 -B -m scripts.run playbook-index
```

A compact JSON array, one record per client: `{slug, summary, aliases, source}`. This is your cross-client memory, loaded every run — each client's one-line critical fact plus brand `aliases`. Read it BEFORE anything else: the brand an operator names often differs from the slug it uploads under (e.g. **ExampleBrand → `example-hub`**). A per-slug body read (Phase 1.5) cannot surface that — you'd need the slug to find the mapping that gives you the slug. Scan every `aliases` and `summary` for the operator's brand; a match hands you the slug directly.

**Step 1 — List registered clients.**

```bash
PYTHONPATH=<skill-dir> python3 -B -m scripts.run list-clients
```

Ask: *"Which client?"* Resolve the operator's brand against BOTH the playbook-index aliases (Step 0) and this client list. Confirm a single strong hit: *"Did you mean **<display_name>** (`<slug>`)?"* and wait.

**No match -> onboarding.** NEVER ask for credentials in chat:

```bash
WS=$(PYTHONPATH=<skill-dir> python3 -B -m scripts.run show-workspace | python3 -c 'import sys,json;print(json.load(sys.stdin)["root"])')
cp $WS/data/secrets/.env.example $WS/data/secrets/_pending.json
# Operator edits _pending.json with real WP creds in their own editor.
# Wait for them to confirm. Then:
PYTHONPATH=<skill-dir> python3 -B -m scripts.run onboard --from-file $WS/data/secrets/_pending.json
```

The CLI reads the file, verifies against WP, writes `data/secrets/<slug>.json` (chmod 600), deletes `_pending.json`. Slug auto-derived from `site_url`. It reports the detected editor — if it says **DEFAULTED** (it couldn't probe), tell the operator to verify the editor in WP admin.

**Slug collision:** the slug is the host's first label, so two sites sharing it (e.g. `acme.com` and `acme.org`) would collide. The CLI **refuses** to overwrite a different client and tells you to disambiguate — re-run with an explicit slug:

```bash
PYTHONPATH=<skill-dir> python3 -B -m scripts.run onboard --from-file $WS/data/secrets/_pending.json --slug <distinct-slug>
```

Re-onboarding the *same* site (same root, new credentials) is allowed — that's a refresh, not a collision.

**URL tolerance:** the CLI normalizes `site_url` on entry. Operators can paste any of these and the same clean root is stored: `https://client.com`, `https://client.com/`, `https://client.com/wp-admin`, `https://client.com/wp-login.php`. Sub-directory installs like `https://client.com/blog` (and a site that genuinely lives under `/admin`) are left alone.

**Security:** NEVER `cat` or `Read` `_pending.json` yourself. Only the CLI handles it.

## Phase 1.5 — Recall past lessons (skip-if-empty)

```bash
SLUG=<slug>
test -f $WS/data/playbooks/$SLUG.md && cat $WS/data/playbooks/$SLUG.md
```

Step 0 already gave you this client's one-line `summary`; this is the full journal — the dated detail behind it. The `summary:`/`aliases:` frontmatter at the top is exactly what the index reads; the `## YYYY-MM-DD` entries below are the depth. If the playbook flags a known brief quirk for this client (e.g. "sometimes URL row is missing"), apply it. Skip silently if none.

## Phase 2 — Pick the brief

Ask: *"Which brief in `briefs/upload/`?"* Accept filename only — `.docx` or `.md`. Prefer `.docx` when both exist (it preserves the table-wrapped body that `.md` flattens).

The file may contain one or many sections. Pre-scan (auto-detects format by extension):

```bash
PYTHONPATH=<skill-dir> python3 -B -m scripts.run list-briefs --doc $WS/briefs/upload/FILENAME.docx
```

Output is a JSON array, one entry per section. There are three section shapes the parser recognizes — you don't choose, it detects:

- **Single brief**: one section → proceed directly, no `--brand`.
- **Multi-brief / multi-body**: several entries. Sources: a `.docx`/`.md` with several `### **Brand**` clients, OR a `.docx` translation file (one topic's ZH original + EN `TRANSLATED VERSION`, each a separate body), OR a multi-client `.docx` with `Heading3` brand markers. Match the operator's chosen client/topic against the `brand` field and pass it as `--brand` in Phase 3. The `brand` string may be a brand name, a `Brand (LANG)` label, or a page title — **pass it exactly as `list-briefs` reported it** (matching is case-insensitive but otherwise exact). Show the list and ask if ambiguous:

  > *"This file has N sections: [list]. Which one?"*

- **Empty array `[]`**: only happens for a `.md` that drifts from every schema (a `.docx` that fails parses with a clear error instead, or returns its sections). For a `.md`, drop into **Phase 2b** below. **First, check whether a `.docx` of the same brief exists** — if so, just use that; it almost certainly parses natively and saves all the Phase-2b work.

## Phase 2b — Markdown fallback (only for a `.md` that returns `[]`)

> **`.docx` briefs never need this.** The Word reader handles the house template (table-wrapped body, Roman-numeral field tables, full-width colons, in-body tables, native bullet lists) natively. Phase 2b exists only for a `.md` file that drifts from every schema **and** has no `.docx` twin. If a `.docx` exists, use it and skip this phase.

The canonical `.md` schema (see [`REFERENCE.md`](REFERENCE.md)): an H3 brand header (bold optional), a pipe table with URL/H1/Meta Title/Meta Description/Keywords/Word count, body with `**H1:/H2:/H3:**` headings. When a `.md` drifts from that and there's no `.docx`, *you* interpret it.

### Step 1 — Map the brief

```bash
PYTHONPATH=<skill-dir> python3 -B -m scripts.run inspect-brief --doc $WS/briefs/upload/FILENAME.md
```

Returns `{section_headers, tables, headings, paragraph_count, list_count}`. Use it to locate the URL / H1 / Meta / Keywords table and the body headings. Read the source `.md` directly for prose — never paraphrase. (`inspect-brief` is markdown-only; it refuses `.docx` because those parse natively.)

### Step 2 — Choose a route

**Work silently — never leave a file behind.** Both routes write to a **temporary path outside the workspace** (your system temp dir), upload from it, then delete it. Do NOT create `*-normalized.md` or `_prepared_*.json` inside `briefs/upload/` or `data/` — a stray file there confuses the non-technical operator ("what's this? did I make it?"). If one ever gets created, remove it.

| Route | When to use |
|---|---|
| **A: Normalize (default)** | `.md` is one or two mechanical fixes from the schema (add bold to a brand header, fix a heading level, strip escape backslashes). Structural correction, not content editing — apply without confirmation. |
| **B: Emit JSON payload (escape hatch)** | `.md` is structurally alien and rewriting costs more than extracting fields directly. Rare. |

### Route A — Normalize (to a temp file)

Write a schema-matching `.md` (see [`REFERENCE.md`](REFERENCE.md) § "Markdown brief format") to a temp path, e.g. `/tmp/<stem>-normalized.md`. Upload from there, then delete it:

```bash
TMP=$(mktemp --suffix=.md)
# ... write the normalized markdown into $TMP ...
PYTHONPATH=<skill-dir> python3 -B -m scripts.run upload --client <SLUG> --doc "$TMP"
rm -f "$TMP"
```

### Route B — Emit JSON payload (to a temp file)

Build a `ParsedDoc`-shape JSON payload (schema in [`REFERENCE.md`](REFERENCE.md) § "ParsedDoc JSON schema") in a temp file, upload, delete:

```bash
TMP=$(mktemp --suffix=.json)
# ... write the ParsedDoc JSON into $TMP ...
PYTHONPATH=<skill-dir> python3 -B -m scripts.run upload-prepared --client <SLUG> --from-file "$TMP"
rm -f "$TMP"
```

Same stdout shape as `upload`.

### Verbatim rule

**Copy body prose word-for-word from the source brief. Never paraphrase, summarise, or "improve" the writer's text.** The writer already approved every word; your job is structural mapping, not content rewriting. Only normalize: heading levels, list markers, escape characters (`\!` -> `!`), pipe-in-cell artifacts.

## Phase 3 — Upload as draft

One command, auto-detects `.docx`/`.md`. Commits immediately (no preview, no `--apply`):

```bash
PYTHONPATH=<skill-dir> python3 -B -m scripts.run upload \
  --client <SLUG> \
  --doc $WS/briefs/upload/FILENAME.docx \
  --brand "<Brand or section label exactly as list-briefs reported>"
```

Drop `--brand` if the file has a single section. Stdout includes a `warnings` array — **surface any warnings to the operator** (e.g. "empty body", "skipped over-long keyword", a defaulted editor). An empty-body or missing-H1 brief fails with a clear error rather than posting a blank draft.

**Images (optional).** If the operator also provides image files (commonly a separate folder — briefs rarely embed placeable images), add `--media-dir` to upload them. Every image in the folder is uploaded in filename order, appended to the body, and the **first becomes the featured image**:

```bash
PYTHONPATH=<skill-dir> python3 -B -m scripts.run upload \
  --client <SLUG> \
  --doc $WS/briefs/upload/FILENAME.docx \
  --media-dir $WS/briefs/upload/<image-folder>
```

The filename stem is a placeholder `alt` — tell the operator to refine alt text + final placement in WP admin. A per-image failure is a warning (surfaced in `warnings`), not a fatal error. When you already know exact placement, put `image` blocks in an `upload-prepared` payload instead (see REFERENCE.md).

Stdout is JSON `{title, post_id, post_url, edit_url, brand, warnings, media}` (`media` lists the uploaded images). Capture it and report to the operator:

> Draft created: **<title>**
> Edit URL: `<edit_url>`
>
> Remember to fill the Yoast / RankMath meta description in the WP editor before publishing — it doesn't sync over REST.

## Phase 4 — (Optional) Record a lesson

Only if you discovered something non-obvious about this client or brief format. Skip for predictable runs:

```bash
PYTHONPATH=<skill-dir> python3 -B -c "
from scripts.tools.playbook import append_lesson
append_lesson(slug='<slug>',
              headline='<one-line>',
              body='''<1-3 sentences>''')
"
```

**If the lesson is a headline-level fact that must load on EVERY run — above all a brand→slug mapping** (operator names a brand that uploads under a different slug) — also pass `summary=` and `aliases=`. They land in the always-loaded index (Phase 1, Step 0), so next time the mapping surfaces *before* client pick instead of being buried in a slug you don't know yet:

```bash
PYTHONPATH=<skill-dir> python3 -B -c "
from scripts.tools.playbook import append_lesson
append_lesson(slug='example-hub',
              headline='ExampleBrand (all langs) map to example-hub',
              body='''Multilingual WP install; REST drafts default to the first language — set language + Yoast by hand.''',
              summary='ExampleBrand (multiple languages) → example-hub; one multilingual install, drafts default to the first language.',
              aliases=['examplebrand'])
"
```

To fix an index line *without* adding a dated entry, call `set_meta(slug, summary='...', aliases=[...])` instead of `append_lesson`.

## Hard rules

- **NEVER** auto-publish — the CLI hardcodes `status=draft`.
- **NEVER** ask the operator to paste credentials in chat.
- **NEVER** read `data/secrets/_pending.json` or `data/secrets/<slug>.json` yourself — only the CLI handles them.
- **NEVER** install pip packages — the skill is pure stdlib.
- **NEVER** write scratch Python scripts inside the workspace.
- **DO NOT** describe the body content back to the operator before uploading. They check it in WP admin.

## Reference

- Full agent SOP: `~/blog-upload/REFERENCE.md`
- CLI help: `PYTHONPATH=<skill-dir> python3 -B -m scripts.run --help`
- DB schema: `~/blog-upload/scripts/schema.sql`
