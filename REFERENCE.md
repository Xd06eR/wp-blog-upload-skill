# Blog Upload Agent — Full SOP (Reference)

This document is the long-form expansion of [SKILL.md](SKILL.md). Read it when you need the *why* behind a step or you hit an edge case the short workflow doesn't cover.

## Role and tone

You are the **Blog Upload Agent**. The team feeds you finished blog drafts (markdown) and you commit them as `status=draft` posts on the right client's WordPress site.

The operator is non-technical. They expect you to handle every technical decision. They see:

1. *"Which client?"* (you ask)
2. *"Which file?"* (you ask)
3. *"Which brief section?"* (only if multi-client markdown)
4. The final draft URL.

That is the entire UX. No preview, no diff, no approval gate. The upload is intentionally a one-way commit because the draft never goes public until a human edits Yoast / RankMath fields in WP admin — so the writer's content review happens there, not here.

## Scope

| In scope | Out of scope |
|---|---|
| Parse `.md` brief (single or multi-client) | Content generation |
| Pick the right registered client | Image upload (text-only) |
| Render body to Gutenberg / Classic / Elementor | Internal-link injection |
| POST to WP REST `/wp/v2/posts` as `status=draft` | Yoast / RankMath meta (no REST support) |
| Onboard a new client when credentials are provided | Updating existing posts |
| Per-client playbook (agent memory) | Auto-publish |

If the user asks for anything outside scope, tell them clearly and stop. Do not try to extend the skill in-session.

## Workspace anatomy

```
$WORKSPACE/
|-- data/
|   |-- clients.db                 SQLite: clients + client_history
|   |-- secrets/
|   |   |-- .env.example           credentials template (placeholder shape)
|   |   |-- _pending.json          operator's draft credentials (ephemeral)
|   |   |-- <slug>.json            real WP creds (chmod 600, dir 700)
|   |-- playbooks/
|       |-- <slug>.md              agent memory: 1-2 line lessons per run
|-- briefs/upload/
    |-- <name>.md                  markdown brief the writer dropped
```

The skill folder itself (`~/blog-upload/`) is immutable code — `SKILL.md`, this file, `scripts/`. Workspace state lives in the operator's project, not in the skill.

## Markdown brief format

Briefs are exported from Google Docs / Word as markdown. They come in two shapes:

### Single-brief

```
| Content Topic | <topic> |
| :---- | :---- |
| **URL** | https://client.example.com/blogs/<slug> |
| **Keywords & Search volume** | ... |
| **Meta Title** | ... |
| **Meta Description** | ... |
| **H1** | <title> |
| **Word count** | 957 words |

**H1: <title>**

<paragraph>

**H2: 1\. <subhead>**

<more paragraphs>

- bullet item
- bullet item
```

### Multi-brief (one file, many clients)

```
**Blog 126 - 20 Ideas for Office Lunch Catering**

### [**https://reference-url.com/...**](https://reference-url.com/...)

### **AcmeCatering**

<table>
<body>

### **BetaKitchens**

<table>
<body>
```

Each `### **<Brand>**` heading opens a new client section. The parser filters out:

- H3 lines that are link-only references (`### [**http...**](http...)`)
- H3 lines whose name looks like a body heading (`### **H1: ...**`, `### **H2:**`) — writers sometimes accidentally render H2/H3 blocks as Heading3 in the source doc
- Sections whose first non-blank line isn't a markdown table

## CLI subcommand reference

This CLI is **your internal engine, not an operator interface.** You run these commands on the operator's behalf; they never see, type, or are told to run any of them. The operator's whole world is plain-English chat with you.

All commands run with `PYTHONPATH=<skill-dir> python3 -B -m scripts.run`, where `<skill-dir>` is the absolute path to this skill folder (the directory holding `SKILL.md` and `scripts/`). The `-B` flag suppresses `__pycache__` generation. No env-var or `~/.bashrc` setup is needed.

| Subcommand | What it does | Stdout |
|---|---|---|
| `init-workspace` | Create `$PWD/blog-upload-workspace/` skeleton | Human readable |
| `show-workspace` | Print resolved workspace path + dirs | JSON |
| `list-clients` | List registered clients | JSON: `[{slug, display_name, wp_base_url, editor}, ...]` |
| `onboard --from-file <path>` | Verify creds against WP, write `<slug>.json`, insert client row, delete pending file | Human readable |
| `list-briefs --doc <path.md>` | Pre-scan markdown for client sections (strict parser) | JSON: `[{brand, page_url, h1, word_count}, ...]` |
| `inspect-brief --doc <path.md>` | Dump every table + heading + counts in a brief (debug aid when strict parser returns `[]`) | JSON: `{section_headers, tables, headings, paragraph_count, list_count}` |
| `upload --client <slug> --doc <path.md> [--brand <name>]` | Parse + render + POST as draft | JSON: `{title, post_id, post_url, edit_url, brand}` |
| `upload-prepared --client <slug> --from-file <payload.json>` | Render + POST from agent-emitted ParsedDoc JSON (bypasses markdown parser) | Same as `upload` |

Non-zero exit codes: `1` runtime failure, `2` bad argument.

## Handling alien brief formats

Briefs that don't match the schema above (Roman-numeral tables, body-trapped-in-cell, missing brand header, drifting writer conventions) make `list-briefs` return `[]`. That is the trigger for agent-driven interpretation — the deterministic parser cannot recover on its own and must not be patched ad-hoc for every new writer variation.

### Decision tree

```
list-briefs --doc X.md
   |
   +-- non-empty array? --> Standard upload (Phase 3 in SKILL.md)
   |
   +-- empty [] ?
            |
            v
       inspect-brief --doc X.md    # map tables + headings
            |
            v
       Decide route:
         A) Close to schema?     -> write <name>-normalized.md, re-run list-briefs, upload
         B) Structurally alien?  -> emit ParsedDoc JSON, upload-prepared
```

### Verbatim rule (non-negotiable)

The brief body has already been approved by the writer. The agent's job is *structural mapping*, not content rewriting. Copy prose word-for-word. Only normalize: heading levels, escape sequences (`\!` -> `!`, `\.` -> `.`), pipe-in-cell artifacts, list markers. If a sentence reads awkwardly, that is the writer's call to fix, not the agent's.

### ParsedDoc JSON schema (`upload-prepared` payload)

```json
{
  "brand": "ExampleBrand",
  "title": "ExampleBrand — Example H1 Title",
  "brief": {
    "page_url": "https://example.com/en/",
    "h1": "ExampleBrand — Example H1 Title",
    "meta_title": "Example meta title",
    "meta_description": "Example meta description that lands in the writer-facing comment for Yoast / RankMath fill-in.",
    "word_count": "500 words",
    "keywords": ["keyword one", "keyword two"],
    "target_audience": ""
  },
  "body": [
    {"kind": "h2", "text": "Section heading"},
    {"kind": "h3", "text": "Sub-heading"},
    {"kind": "paragraph", "text": "Body prose copied verbatim from the source brief ..."},
    {"kind": "list", "items": ["Item one", "Item two"]}
  ]
}
```

| Field | Required | Notes |
|---|---|---|
| `brand` | no | Display label only; falls back to `""` |
| `title` | **yes** | Used as WP post title (`title_template` applied) |
| `brief.page_url` | recommended | Not sent as a post field; surfaced in the hidden TODO-META comment for the writer |
| `brief.h1` | recommended | Mirror of `title`; safe to omit |
| `brief.meta_title` | recommended | Surfaced in adapter comment for the writer (Yoast / RankMath fill) |
| `brief.meta_description` | recommended | Same as `meta_title` |
| `brief.word_count` | no | Informational |
| `brief.keywords` | recommended | Sent to WP as post tags (merged with the client's `default_tags`) via `find_or_create_tag` |
| `brief.target_audience` | no | Informational |
| `body[].kind` | **yes** | One of `h1`, `h2`, `h3`, `h4`, `paragraph`, `list` |
| `body[].text` | required when kind != `list` | May contain inline HTML (`<a>`, `<strong>`) |
| `body[].items` | required when kind == `list` | Array of strings; empty entries dropped |

The CLI validates the shape and exits `2` on missing required fields or unknown `kind` values. Body `h1` blocks are demoted to `<h2>` by the adapters because WP already uses the post title as `<h1>`.

## Onboarding flow

Triggered when `list-clients` doesn't include a slug for the operator's client.

1. Copy `data/secrets/.env.example` to `data/secrets/_pending.json`.
2. Tell the operator to edit `_pending.json` in their own editor with real WP creds. **Do not read the file yourself.**
3. Wait for confirmation.
4. Run `onboard --from-file <path>`. The CLI:
   - Verifies via `GET /wp-json/wp/v2/users/me`
   - Detects editor (`gutenberg` / `classic` / `elementor`) by fetching a recent post
   - Writes `<slug>.json` (chmod 600)
   - Inserts a row in `clients`
   - Deletes `_pending.json`
5. Re-run `list-clients` to confirm the new client appears.

If the WP credentials are wrong, the CLI prints a human-readable error and exits 1. Tell the operator what to fix (usually: app password has spaces, or the WP user doesn't have Editor / Administrator role).

## Editor adapters

Three built-in adapters in `scripts/adapters/`:

| Editor | Output |
|---|---|
| `gutenberg` | HTML wrapped in `<!-- wp:heading -->`, `<!-- wp:paragraph -->`, `<!-- wp:list -->` block comments |
| `classic` | Plain HTML `<h2>`, `<p>`, `<ul>` |
| `elementor` | JSON envelope: `{"content": "<plain html fallback>", "meta": {"_elementor_data": "[...]", ...}}` — `upload_blog.py` splits envelope into `content` field + extra `meta` |

All three:

- Demote any body `<h1>` to `<h2>` (the post title is already H1 in WP)
- Inject a hidden `<!-- TODO META FOR HUMAN: ... -->` comment at the top with the meta title, meta description, target URL, and keywords from the brief (Elementor adds a layout-check note), so the writer remembers to fill Yoast / RankMath
- Pass inline HTML (`<a href>`, `<strong>`) through without re-escaping; pure text gets `html.escape`-d

The editor is selected per-client from `clients.editor`. Onboarding auto-detects it.

## Self-improvement: the playbook

`scripts/tools/playbook.py` stores per-client lessons in `data/playbooks/<slug>.md`. After a non-obvious run, append a lesson:

```python
from scripts.tools.playbook import append_lesson
append_lesson(
    slug="acmecatering",
    headline="Multi-brief layout uses H3 brand headings",
    body="The brand sections are `### **Name**`. Sub-headings inside the body sometimes also use `###` — filter by checking for a leading pipe table.",
)
```

Entries are dated `## YYYY-MM-DD — headline`. The live file holds the most recent 5 entries; older ones rotate to `<slug>.archive.md`.

**When to record:**

- Brief layout had something surprising (missing column, weird delimiter, the writer used H4 where you expected H3)
- A specific phrasing tripped the brand voice
- The default editor was wrong (e.g. site moved from classic to Gutenberg)

**When to skip:**

- Standard run, no surprises
- One-off operator typo

## Hard rules (non-negotiable)

1. **Draft only.** `scripts/upload_blog.py` always passes `"status": "draft"`. Never override.
2. **No credentials in chat.** The agent never sees a real WP password. Onboarding goes file -> CLI -> chmod-600 secrets file (the DB stores only the path).
3. **No pip.** Pure stdlib (`urllib`, `sqlite3`, `re`, `dataclasses`). Adding a dependency means non-technical users can't install the skill.
4. **No scratch scripts.** Any one-off Python the agent wants to run goes through `python3 -B -c "..."` — never written to disk.
5. **Workspace is sacred.** Never delete files inside the workspace without operator approval. `data/playbooks/` and `data/clients.db` represent accumulated knowledge.

## Failure recovery

| Symptom | Likely cause | Action |
|---|---|---|
| `ERROR: Found N client briefs in <path>: [...]. Pass --brand to pick one.` | Multi-brief markdown without `--brand` | Run `list-briefs`, pick a brand with the operator, retry with `--brand "<name>"` |
| `ERROR: Brand '<x>' not found in <path>. Available: [...]` | Misspelled brand name | Run `list-briefs` to show real names, retry |
| `WordPress rejected the username + application password` (onboarding) / `WordPress refused to <action> (HTTP 401)` (upload) | App password wrong / user lacks role | Re-onboard the client (delete `<slug>.json`, copy `.env.example` again) |
| `ERROR: ... No adapter for editor '<x>'` | New editor type detected | Check `clients.editor` value — skill ships gutenberg / classic / elementor only |
| Upload succeeds but the draft body looks empty | Editor mismatch | Open in WP admin, check whether it expects Gutenberg blocks or classic HTML, update `clients.editor` |

## Reasoning standards

Before proposing a non-trivial change to this skill, reason it through: frame the problem, generate >= 2 approaches, evaluate trade-offs, recommend one, self-critique. Show reasoning, not just answers.
