# WordPress Blog Upload Skill

An **AI agent skill** that uploads markdown blog briefs to WordPress as draft posts — eliminating the copy-paste step between Google Docs and WordPress admin. You drive it in plain English; the agent does the rest.

**Works with any AI coding agent** that can run a shell — Claude Code, GitHub Copilot, Codex, Kimi Code, Antigravity, opencode, and others. Under the hood the agent drives a pure-Python CLI, but **that CLI is the agent's internal engine — operators never type a command, and the prompt templates work the same in every agent.** Examples in these docs use Claude Code's `@` shortcut.

> 👉 **Just want to use it — no coding?** Open **[`GUIDE.html`](GUIDE.html)** in your browser for a step-by-step, plain-English guide. You talk to the agent; you never touch a terminal. The rest of this README is maintainer context for whoever installs or extends the skill.

The agent parses a `.md` brief, picks the right client from a local SQLite store, renders the body for the client's editor (Gutenberg, Classic, or Elementor), and POSTs straight to WordPress as `status=draft`. No preview, no approval gate — the writer reviews and fills Yoast / RankMath meta in WP admin, which they have to do anyway.

## Features

- **Single- or multi-client briefs** — one `.md` file can hold briefs for several brands; the agent filters by brand heading (`### **BrandName**`).
- **Flexible brief intake** — a strict parser handles the canonical schema, and an **agent-driven fallback** absorbs alien formats (Roman-numeral tables, body-in-cell, missing brand header, drifting writer conventions). The agent maps the brief via `inspect-brief`, then either normalizes it on disk or emits a `ParsedDoc` JSON straight to `upload-prepared` — body prose is copied verbatim, never paraphrased.
- **Per-client editor adapters** — auto-detects and renders Gutenberg blocks, Classic HTML, or Elementor JSON envelopes.
- **SQLite client registry** — onboard new clients via a JSON file; credentials are verified against WP REST before storage.
- **Pure Python stdlib** — no `pip install`, no virtualenv. Copy the skill folder and go.
- **Per-client playbook** — agent memory stored as markdown lessons so repeat quirks (e.g. "this writer always omits the URL row") are handled automatically.
- **Hardcoded draft-only** — the CLI refuses to auto-publish. Every upload lands in `status=draft`.

## How it works

```text
Operator drops .md brief ──▶ Agent picks client ──▶ list-briefs (strict parser)
                                                            │
                       ┌────────────────────────────────────┤
                       ▼                                    ▼
                  match found                          empty [] → alien format
                       │                                    │
                       │                            inspect-brief (map tables/headings)
                       │                                    │
                       │              ┌─────────────────────┴─────────────────────┐
                       │              ▼                                           ▼
                       │   Route A: rewrite as <name>-normalized.md    Route B: emit ParsedDoc JSON
                       │              │                                           │
                       │              ▼                                           ▼
                       │       (re-enters strict path)                    upload-prepared
                       │              │                                           │
                       └──────────────┴───────────────┬───────────────────────────┘
                                                      ▼
                                            Render body (adapter)
                                                      │
                                                      ▼
                                        POST to WP REST /wp/v2/posts
                                                      │
                                                      ▼
                        Draft created ──▶ Writer fills Yoast / RankMath in WP admin
```

**First-time client onboarding** (one-time per new client, runs before the flow above when the client isn't registered yet):

```text
Client not in registry
        │
        ▼
Operator pastes WP creds into a local file   (never into the chat)
        │
        ▼
CLI verifies them against WP REST  ──fail──▶  agent explains what to fix
        │ ok
        ▼
Stored as chmod-600 JSON on disk   (SQLite records only the path, not the secret)
        │
        ▼
Back to the main flow — agent picks this client
```

## Project Structure

The repo root **is** the skill — clone it directly, no `skill/` subfolder.

```text
blog-upload/                ← repo root == the skill
├── README.md               ← you are here
├── CLAUDE.md               ← maintainer / developer context
├── SKILL.md                ← agent workflow (what the agent follows)
├── REFERENCE.md            ← full SOP, CLI reference, failure recovery
├── GUIDE.md / GUIDE.html   ← non-technical guide for end users
├── scripts/                ← Python package (pure stdlib)
│   ├── run.py              ← CLI entrypoint
│   ├── upload_blog.py      ← orchestrator
│   ├── schema.sql          ← SQLite DDL (clients + client_history)
│   ├── adapters/           ← gutenberg, classic, elementor
│   └── tools/              ← parse_md, wp_client, workspace,
│                             client_store, client_config, onboarding, playbook
└── tests/                  ← stdlib unittest
```

Workspace (auto-created on first run in the operator's working directory):

```text
blog-upload-workspace/
├── data/
│   ├── clients.db
│   ├── secrets/<slug>.json      (chmod 600, never commit)
│   ├── secrets/.env.example
│   └── playbooks/<slug>.md
└── briefs/upload/<name>.md
```

## Installation

> Installation is a one-time maintainer step. **Operators never do this** — they just ask the agent (see [`GUIDE.html`](GUIDE.html)), and the agent clones and sets up the skill on their behalf.

### 1. Clone the repo

```bash
git clone https://github.com/Xd06eR/wp-blog-upload-skill.git ~/blog-upload
```

The repo root *is* the skill, so this puts everything at `~/blog-upload/` — there is no separate copy/install step.

### 2. Use it

Launch your AI coding agent (Claude Code, GitHub Copilot, Codex, Kimi Code, Antigravity, …) from your home folder (`~/`) and **explicitly invoke the skill** — tag it in Claude Code, or name it ("use the blog-upload skill") in other agents:

```text
@blog-upload upload @my-brief.md for <Client>
```

Non-technical operators: open `GUIDE.html` in a browser and follow it step by step.

> **Keep the skill in your working directory and invoke it explicitly.** Installing it into `~/.claude/skills/` for auto-discovery is **not recommended** — auto-invoke can fire on unrelated tasks or fail to trigger mid-upload. Explicit tagging is deterministic.

### 3. Get the latest version

```bash
cd ~/blog-upload && git pull
```

Because the skill runs straight from the clone, `git pull` is the entire update — no re-copy, no reinstall.

## Workspace location

Runtime state (clients, credentials, briefs) lives in a `blog-upload-workspace/` folder, separate from the skill. The CLI finds it like this: the nearest `blog-upload-workspace/` in a sub-folder of where you launched (downward search), otherwise it's created in the current folder (`$PWD/blog-upload-workspace`).

You can **move or rename the workspace freely** — credential paths are stored relative to it and resolved at load time, so nothing breaks.

## Safety

- **Draft only** — `status=draft` is hardcoded in `upload_blog.py`.
- **No credentials in chat** — you put WP creds into a local file in your own editor; they never pass through the chat, the command line, or any CLI output. The agent is instructed never to open the credential files. Creds are stored as a **plaintext `chmod 600` file on disk** (SQLite holds only the *path*), protected by OS file permissions — not encryption. Use a **revocable WordPress application password** so it can be rotated instantly.
- **No external dependencies** — `urllib`, `sqlite3`, `re`, `dataclasses` only.
- **No scratch scripts** — one-off code runs via `python3 -B -c "..."`, never written to disk.

### Security model & limits

Be clear-eyed about what actually protects the credentials:

- **Plaintext at rest.** The app password is a `chmod 600` JSON file inside a `chmod 700` dir — **not encrypted**. Anyone with that OS account, a stray backup, or a folder sync can read it. WP application passwords are revocable and role-scoped, so rotate immediately if one is exposed.
- **Agent restraint is a guardrail, not a sandbox.** Nothing *technically* stops the agent reading the credential files — it is *instructed* not to. A different agent, a jailbreak, or **prompt injection via a malicious brief** (briefs are untrusted input the agent parses) could read them. Don't run briefs from untrusted sources.
- **Keep secrets out of the model's context.** Don't `@`-mention or let the IDE index `data/secrets/` — that can pull plaintext creds into the agent's context without it ever "deciding" to open the file.
- **Never commit secrets.** `data/secrets/`, `*.db`, `*-workspace/`, `.env`, and `_pending.json` are gitignored; verify before any push.
