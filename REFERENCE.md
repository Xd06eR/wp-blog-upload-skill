# Blog Upload Agent — Full SOP (Reference)

This document is the long-form expansion of [SKILL.md](SKILL.md). Read it when you need the *why* behind a step or you hit an edge case the short workflow doesn't cover.

## Role and tone

You are the **Blog Upload Agent**. The operator feeds you finished blog drafts (`.docx` or `.md`, auto-detected by extension) and you commit them as `status=draft` posts on the right client's WordPress site. `.docx` is the safer default: some briefs wrap the article body in a Word table cell, and markdown export *can* flatten that cell into one line (losing the heading/paragraph structure), while the native `.docx` reader keeps the structure intact.

The operator is non-technical. They expect you to handle every technical decision. They see:

1. *"Which client?"* (you ask)
2. *"Which file?"* (you ask)
3. *"Which brief section?"* (only if a multi-client / multi-body brief)
4. The final draft URL.

That is the entire UX. No preview, no diff, no approval gate. The upload is intentionally a one-way commit because the draft never goes public until a human edits Yoast / RankMath fields in WP admin — so the writer's content review happens there, not here.

## Scope

| In scope | Out of scope |
|---|---|
| Parse `.docx` or `.md` brief (single or multi-client) | Content generation |
| Pick the right registered client | Image *generation* / editing / resizing |
| Render body to Gutenberg / Classic / Elementor | Internal-link injection |
| Upload images + set the first as the featured image | Yoast / RankMath meta (no REST support) |
| POST to WP REST `/wp/v2/posts` as `status=draft` | Updating existing posts |
| Onboard a new client when credentials are provided | Auto-publish |
| Per-client playbook (agent memory) | |

If the user asks for anything outside scope, tell them clearly and stop. Do not try to extend the skill in-session.

## Workspace anatomy

```text
$WORKSPACE/
├── data/
│   ├── clients.db                 ← SQLite: clients + client_history
│   ├── secrets/
│   │   ├── .env.example           ← credentials template (placeholder shape)
│   │   ├── _pending.json          ← operator's draft credentials (ephemeral)
│   │   └── <slug>.json            ← real WP creds (chmod 600, dir 700)
│   └── playbooks/
│       └── <slug>.md              ← agent memory: 1-2 line lessons per run
└── briefs/upload/
    └── <name>.docx | .md          ← brief the writer dropped (.docx or .md)
```

The skill folder itself (`~/blog-upload/`) is immutable code — `SKILL.md`, this file, `scripts/`. Workspace state lives in the operator's project, not in the skill.

## Brief formats

Briefs arrive as `.docx` (Word) or `.md` (markdown exported from Google Docs / Word), auto-detected by file extension. `.docx` is the preferred shape — see "House template" below for why. Writer formats vary, so treat the shapes documented here as the common cases the parser and the `.docx` reader cover, not a single rigid template: when a brief drifts, adapt (see "Handling alien markdown briefs").

### House template (a common body-in-a-table shape)

A common brief layout wraps the body in a table: a generic Date / Client header, Roman-numeral field tables (`I. Page URL`, `II. Keyword(s)`, `IV. Page title`, `V. Meta description`, `VI. Body content`), with the entire article body inside the `VI. Body content` table cell. This is one of several writer formats you may see, not the only one.

This shape **parses natively from `.docx`** — the reader walks the field tables by their Roman-numeral labels and reads the body cell with its headings, paragraphs, in-body tables, Word native bullet lists, and real hyperlinks intact. If a brief is shaped this way, prefer its `.docx` — the `.md` export may flatten the body cell into a single line and lose that structure. If you only have the `.md`, ask for the `.docx`.

### Translation / multi-body `.docx`

A translation brief packs one topic's ZH original plus its EN "TRANSLATED VERSION" into a single `.docx` as two separate bodies. Each body is selected with `--brand`, using the label that `list-briefs` reports for it.

### Images

Briefs rarely carry machine-placeable images — the files usually arrive separately (e.g. a Drive folder of numbered images) with no "insert here" markers. Two paths upload them:

- **Folder (`--media-dir`):** point `upload` at a folder; every image file (`.jpg/.jpeg/.png/.gif/.webp`) is uploaded to the WP media library in filename order, appended to the body, and the **first becomes the post's featured image**. The filename stem is used as a placeholder `alt` — the writer refines alt text + final placement in WP admin.
- **Inline (`upload-prepared`):** when you *do* know placement, put `{"kind": "image", "src": "/abs/path.jpg", "alt": "..."}` blocks directly in the `body[]` array (see "ParsedDoc JSON schema"); each is uploaded and rendered in place.

Either way the skill **uploads** existing image files — it never generates, edits, or resizes them. A per-image upload failure is a warning, not a fatal error: the rest of the draft still posts.

### Markdown shapes

The markdown parser handles two layouts. (Use these when the brief genuinely arrives as `.md`, rather than as an `.md` export of a body-in-a-table house template, whose body cell the export can flatten.)

#### Single-brief

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

#### Multi-brief (one file, many clients)

```
<!-- optional preamble: a blog-set title, a reference link, etc. -->

### **BrandA**

<table>
<body>

### **BrandB**

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
| `playbook-index` | Always-load cross-client memory: one record per playbook — curated `summary` + brand `aliases` (hybrid: falls back to newest headline). Run at Phase 1 **before** client pick to resolve brand→slug | JSON: `[{slug, summary, aliases, source}, ...]` |
| `onboard --from-file <path> [--slug <slug>]` | Verify creds against WP, write `<slug>.json`, insert client row, delete pending file. `--slug` overrides the slug auto-derived from the site URL (use it to resolve a slug collision) | Human readable |
| `list-briefs --doc <path>` | Pre-scan a `.docx` or `.md` brief for client / body sections (strict parser; auto-detected by extension) | JSON: `[{brand, page_url, h1, word_count}, ...]` |
| `inspect-brief --doc <path.md>` | Dump every table + heading + counts in a **markdown** brief (debug aid when strict parser returns `[]`). Markdown-only — refuses `.docx` (a `.docx` parses natively, so there is nothing to inspect) | JSON: `{section_headers, tables, headings, paragraph_count, list_count}` |
| `upload --client <slug> --doc <path> [--brand <name>] [--media-dir <dir>]` | Parse + render + POST as draft (`.docx` / `.md` auto-detected). `--media-dir` uploads every image in the folder (name-sorted), appends them to the body, and sets the first as the featured image | JSON: `{title, post_id, post_url, edit_url, brand, warnings, media}` |
| `upload-prepared --client <slug> --from-file <payload.json>` | Render + POST from agent-emitted ParsedDoc JSON (bypasses the brief parser) | Same as `upload` |

`.docx` briefs are parsed natively — there is no normalize step, and `inspect-brief` does not apply to them. `warnings` is an array of non-fatal advisories (empty-body, defaulted-editor); empty when the run was clean.

Non-zero exit codes: `1` runtime failure, `2` bad argument.

## Handling alien markdown briefs

**First, check for a `.docx`.** The Roman-numeral / body-in-a-cell house template parses natively from `.docx` (see "House template" above), so if a `.docx` exists, use it — the routes below are not needed. The normalization fallback here is **markdown-only**: it applies to a `.md` that drifts from the schema *and* has no `.docx` twin.

A markdown brief that doesn't match the schema above (missing brand header, drifting writer conventions, a body-in-a-table export the flattening hit) makes `list-briefs` return `[]`. Writer formats vary, so expect this; that empty result is the trigger for agent-driven interpretation — the deterministic markdown parser cannot recover on its own and must not be patched ad-hoc for every new writer variation.

### Decision tree

Both routes work in a temp file outside the workspace (mktemp-style) and delete it after upload — never leave a normalized `.md` or a prepared-JSON artifact in the workspace.

```text
.docx twin exists? ──▶ use it (parses natively), skip this tree
   │
   ▼ (markdown only, no .docx)
list-briefs --doc X.md
   │
   ├── non-empty array? ──▶ Standard upload (Phase 3 in SKILL.md)
   │
   └── empty [] ?
            │
            ▼
       inspect-brief --doc X.md          # map tables + headings
            │
            ▼
       Decide route:
         A) Close to schema?     ──▶ normalize to a TEMP .md, upload, delete it
         B) Structurally alien?  ──▶ emit ParsedDoc JSON to a TEMP file, upload-prepared, delete it
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
    {"kind": "list", "items": ["Item one", "Item two"]},
    {"kind": "table", "rows": [["Header one", "Header two"], ["Cell A", "Cell B"]]},
    {"kind": "image", "src": "/abs/path/to/photo.jpg", "alt": "descriptive alt text"}
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
| `brief.keywords` | recommended | Surfaced in the hidden TODO-META comment for the writer to set as Yoast / RankMath keyphrases by hand; **not** auto-tagged. WP post tags come only from the client's `default_tags` |
| `brief.target_audience` | no | Informational |
| `body[].kind` | **yes** | One of `h1`, `h2`, `h3`, `h4`, `paragraph`, `list`, `table`, `image` |
| `body[].text` | required when kind is a heading or `paragraph` | May contain inline HTML (`<a>`, `<strong>`) |
| `body[].items` | required when kind == `list` | Array of strings; empty entries dropped |
| `body[].rows` | required when kind == `table` | Array of rows, each an array of cell-HTML strings; renders as a real `<table>` |
| `body[].src` | required when kind == `image` | Local file path; uploaded to the WP media library at POST time. The first image in the body becomes the post's `featured_media` |
| `body[].alt` | optional (image) | Alt text; defaults to empty |

The CLI validates the shape and exits `2` on missing required fields or unknown `kind` values. Body `h1` blocks are demoted to `<h2>` by the adapters because WP already uses the post title as `<h1>`. On success the `UploadResult` (stdout JSON) carries a `warnings` array — non-fatal advisories such as an empty body or a defaulted editor; empty on a clean run. Image blocks are uploaded to the WP media library at POST time; the result JSON also carries a `media` array of the uploaded `{id, url}` and the first image is set as `featured_media`.

## Onboarding flow

Triggered when `list-clients` doesn't include a slug for the operator's client.

1. Copy `data/secrets/.env.example` to `data/secrets/_pending.json`.
2. Tell the operator to edit `_pending.json` in their own editor with real WP creds. **Do not read the file yourself.**
3. Wait for confirmation.
4. Run `onboard --from-file <path>` (add `--slug <slug>` to override the auto-derived slug). The CLI:
   - Verifies via `GET /wp-json/wp/v2/users/me`
   - Derives the slug from the site URL (or uses `--slug`). It **refuses to silently overwrite a different client that derives the same slug** — on a collision it errors and tells you to pass `--slug`. Re-onboarding the *same* site root is allowed (credential refresh).
   - Detects editor (`gutenberg` / `classic` / `elementor`) by fetching a recent post. Detection is honest: when it can't probe (no posts / probe failed), it defaults to `gutenberg` and surfaces "DEFAULTED — verify in WP admin" instead of pretending it detected.
   - Writes `<slug>.json` (chmod 600)
   - Inserts a row in `clients`
   - Deletes `_pending.json`
5. Re-run `list-clients` to confirm the new client appears.

Note: `_normalize_site_root` strips a trailing `/wp-admin` or `/wp-login.php` from the site URL, but **no longer strips `/admin`** — that is a legitimate subdirectory path for some installs.

If the WP credentials are wrong, the CLI prints a human-readable error and exits 1. Tell the operator what to fix (usually: app password has spaces, or the WP user doesn't have Editor / Administrator role). If the slug collides with an existing different client, re-run with `--slug <slug>`.

## Editor adapters

Three built-in adapters in `scripts/adapters/`:

| Editor | Output |
|---|---|
| `gutenberg` | HTML wrapped in `<!-- wp:heading -->`, `<!-- wp:paragraph -->`, `<!-- wp:list -->` block comments. List items each get their own `<!-- wp:list-item -->` wrapper (WP 6.0+ flags a bare `<li>`), `table` blocks render as a `<!-- wp:table -->` `<figure class="wp-block-table"><table>...</table></figure>`, and `image` blocks as `<!-- wp:image {"id":N} --><figure class="wp-block-image"><img .../></figure>` |
| `classic` | Plain HTML `<h2>`, `<p>`, `<ul>`, a real `<table>` for `table` blocks, and `<figure><img></figure>` for `image` blocks |
| `elementor` | JSON envelope: `{"content": "<plain html fallback>", "meta": {"_elementor_data": "[...]", ...}}` — `upload_blog.py` splits envelope into `content` field + extra `meta`. `image` blocks become an Elementor `image` widget (URL + media id), with an `<img>` in the HTML fallback |

All three:

- Demote any body `<h1>` to `<h2>` (the post title is already H1 in WP)
- Render in-body `table` blocks as real `<table>` markup (not flattened text)
- Render `image` blocks as the editor's native image markup (Gutenberg `wp:image`, Classic/Elementor `<figure><img>`), referencing the file's WP media URL + id after upload; the first image in the body is set as the post's `featured_media`
- Inject a hidden `<!-- TODO META FOR HUMAN: ... -->` comment at the top with the meta title, meta description, target URL, and keywords from the brief (Elementor adds a layout-check note), so the writer remembers to fill Yoast / RankMath. Fields interpolated into that comment are injection-safe: a literal `-->` in a value is neutralized so it can't close the comment early
- Escape literal text spans while preserving recognized inline tags — the inline `<a>` / `<strong>` from the parsers pass through, and only the text between them is `html.escape`-d

The editor is selected per-client from `clients.editor`. Onboarding auto-detects it.

## Self-improvement: the playbook

`scripts/tools/playbook.py` stores per-client lessons in `data/playbooks/<slug>.md`. It exposes **two access layers** (progressive disclosure):

- **Index (always loaded).** `build_index()` — surfaced by the `playbook-index` CLI command — returns one compact record per client: a curated `summary` plus brand `aliases`. The agent loads this on EVERY run at Phase 1 Step 0, *before* picking a client. This is what fixes the brand→slug chicken-and-egg: a mapping like "ExampleBrand → `example-hub`" lives in the index, so it surfaces without already knowing the slug. Hybrid: uses the frontmatter `summary` when set, else the newest lesson headline (so legacy playbooks still say something). The `source` field flags which was used (`summary` | `headline` | `empty`).
- **Body (lazy).** `read(slug)` — the full dated journal for ONE client, loaded only once the client is known (Phase 1.5).

File shape — optional frontmatter carries the index fields; the journal follows:

```markdown
---
summary: ExampleBrand (FR/ES/NL/PT/IT/PL) -> example-hub; one multilingual install, drafts default to IT.
aliases: examplebrand
---
# Playbook — example-hub

## YYYY-MM-DD — headline

<1-3 sentences>
```

Frontmatter is parsed by a tiny stdlib reader (no PyYAML): `key: value` lines between two `---` fences; `aliases` is comma-separated.

After a non-obvious run, append a lesson. Pass `summary` / `aliases` too when the fact should load on every run (especially a brand→slug mapping):

```python
from scripts.tools.playbook import append_lesson
append_lesson(
    slug="acmecatering",
    headline="Multi-brief layout uses H3 brand headings",
    body="The brand sections are `### **Name**`. Sub-headings inside the body sometimes also use `###` — filter by checking for a leading pipe table.",
    summary="AcmeCatering multi-brief — H3 `### **Name**` brand sections; filter by leading pipe table.",  # optional: lands in the always-load index
    aliases=["acme catering"],                                                                            # optional: brand the operator might name
)
```

To curate the index line **without** adding a dated entry (e.g. backfill a mapping onto a legacy playbook), use `set_meta(slug, summary=..., aliases=[...])`; aliases merge by default (`replace_aliases=True` to overwrite). `summary` is capped at 200 chars and must be single-line; `aliases` entries containing a comma are rejected (comma is the frontmatter delimiter).

Entries are dated `## YYYY-MM-DD — headline`. The live file holds the most recent 5 entries; older ones rotate to `<slug>.archive.md`. Frontmatter is preserved across rotation.

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
| Onboarding errors on a slug collision (a different client already derives this slug) | Two clients map to the same auto-derived slug | Re-run `onboard` with an explicit `--slug <slug>` |
| Upload fails loud on an empty body / missing H1 | Brief parsed to no body content (e.g. an `.md` export of a body-in-a-table brief where the export may have flattened the body cell) | Use the `.docx` instead; if markdown-only, normalize it (Route A) or emit ParsedDoc JSON (Route B) so the body is populated |
| `warnings` includes `Image upload failed for <file>` | Image file missing/unreadable, or WP rejected it (size / MIME / media permissions) | Confirm the file exists and the WP user can upload media, then re-run; the draft still posts without that image |
| `ERROR: --media-dir is not a directory: <path>` | `--media-dir` pointed at a missing folder or a file | Pass the folder that holds the image files |
| `ERROR: ... No adapter for editor '<x>'` | New editor type detected | Check `clients.editor` value — skill ships gutenberg / classic / elementor only |
| Upload succeeds but the draft body looks empty | Editor mismatch | Open in WP admin, check whether it expects Gutenberg blocks or classic HTML, update `clients.editor` |

## Reasoning standards

Before proposing a non-trivial change to this skill, reason it through: frame the problem, generate >= 2 approaches, evaluate trade-offs, recommend one, self-critique. Show reasoning, not just answers.
