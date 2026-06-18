# Blog Upload — Easy Guide (for non-technical users)

Hi! This guide shows you how to upload blog drafts to a client's WordPress site using an **AI coding agent** — Claude Code, GitHub Copilot, Codex, Kimi Code, Antigravity, opencode, whichever your team uses. **You don't need to know any code — you just type plain-English prompts.**

What the tool does for you:
- Reads your blog brief (a Word `.docx` file — or a Markdown `.md` file).
- Picks the right client — and if it's a **new** client, walks you through setting it up.
- Creates a **draft** post on WordPress (it never publishes — you do that yourself).

**What you normally tell it:** the **client name** + the **brief file**. That's all. The agent asks you for anything else it needs (which section to use, a missing login, etc.).

> Works on Mac, Windows, and Linux. **Launch your agent from your work folder** — the first time, it creates the workspace there; after that it finds it automatically (even from sub-folders).

---

## How you talk to your agent

**Tag the skill and your brief when you ask** — that's how the agent knows to use *this* tool instead of guessing. Most agents share the `@`-mention convention: type `@` and pick the name. Tag the skill (`@blog-upload`) and point at your brief the same way (`@my-brief.docx`). The exact tagging syntax can vary by agent — if `@` doesn't bring up a picker, check how your agent references files and skills.

> 💡 **Keep the `blog-upload` folder in your working directory and tag it explicitly.** Don't rely on the agent auto-detecting it — auto-invoke can misfire (trigger when you don't want it, or stay quiet during an upload when you do).

Example:

> `@blog-upload upload @my-brief.docx for Acme Catering`

The agent does the rest — reads the brief, finds the client, and creates the draft.

---

## 📋 Ready-Made Prompts (copy-paste — works in any agent)

Each prompt pairs plain English with the exact command, so the agent acts reliably. Copy-paste the whole block into the chat — the **agent** runs the command, not you.

**① Set up the skill — first time only**

> Clone the blog-upload skill and set up its workspace for me. Run `git clone https://github.com/Xd06eR/wp-blog-upload-skill.git blog-upload`, then go into the `blog-upload` folder and initialize the workspace.

**② Upload a blog** — same prompt in any agent; only the way you tag the file may differ.

> `@blog-upload` upload `@‹your-brief.docx›` for `‹Client Name›`

> - The skill always uploads as a **draft** and gives you back the draft link — you don't need to ask for either.
> - If the file has sections for several clients, the agent shows the list and asks which one.
> - If the client is new, the agent notices and walks you through adding it (it asks you for the WordPress site address, username, and an application password).

**③ Update the skill to the latest version**

> Update my blog-upload skill to the latest version: run `git pull` inside the `blog-upload` folder, then tell me what changed.

> 💡 **If anything ever looks off, just tell the agent in plain English what happened** ("the upload failed — what went wrong?"). It explains, fixes it, or asks you for what it needs. You never have to memorize commands or troubleshoot yourself.

---

## 🗒️ Your First Day Checklist

- [ ] **Step 1.** Set up the skill + workspace (prompt ① above) — *one-time*
- [ ] **Step 2.** Get your blog brief as a Word file (`.docx`)
- [ ] **Step 3.** Upload it (prompt ②) — the agent handles the rest
- [ ] **Step 4.** Open the draft in WordPress, fill the meta, hit Publish

After today you only repeat Steps 2–4.

---

## Step by step

### Step 1 — Get the skill + workspace (one time)

**Just ask your agent:** paste prompt ① above. It clones the skill **and** sets up the workspace — a `blog-upload-workspace` folder where your briefs and saved client info live. You never open a terminal or manage that folder by hand.

### Step 2 — Get your brief as a Word file (.docx)

Word (`.docx`) is the **recommended, safe default** — download the Google Doc as Word and hand that to the agent.

> 💡 **Why Word, not Markdown?** Some briefs put the blog body **inside a table** in the Google Doc. When they do, downloading as Markdown can flatten that table and lose the headings and paragraphs — so the draft may come out wrong. Downloading as **Word (.docx)** keeps everything — headings, paragraphs, tables, bullet lists, and links — so it's the safer choice either way.

**Download the whole brief as Word (do this):**
1. Open the brief in **Google Docs**.
2. **File → Download → Microsoft Word (.docx)**.
3. It lands in your Downloads folder (e.g. `my-blog-brief.docx`). Hand that file to the agent.

**Alternative — Markdown (`.md`), for simple posts only:** the skill still accepts Markdown, and it's fine when the brief has no table around the body. To get it: **File → Download → Markdown (.md)**, *or* turn Markdown on (**Tools → Preferences → tick "Enable Markdown" → OK**) and use **Edit → Copy as Markdown**, then paste into a plain-text editor and save with a `.md` ending. When in doubt, use Word — it's the safer choice.

### Step 3 — Upload it

**Easiest — ask your agent** (paste prompt ②, or use your agent's file shortcut). Give the **client name** + the **file**. The agent then:
- finds the client (or sets it up if it's new — asking you for the login),
- asks which section if the file has several,
- creates the draft and gives you the **edit link**.

Your brief's wording is always copied **word-for-word** — the agent never rewrites your writer's content. If a brief's layout is unusual the agent sorts it out automatically; if it's genuinely unreadable it stops and asks you to check, rather than guessing.

### Step 4 — Finish in WordPress

Open the **edit link** the agent gives you, then in WP admin:
1. Fill the **Yoast / RankMath meta title + description** (these can't be set automatically — do it by hand).
2. Add a featured image, internal links, etc.
3. When happy, hit **Publish** yourself.

🎉 Done.

---

## Keeping the skill updated

**Just ask your agent:** paste prompt ③ above. The agent updates the skill and tells you what changed — nothing for you to run.

---

## What NOT to do

- ❌ Don't paste WordPress passwords into the chat — the agent will tell you to put them in a file instead.
- ❌ Don't hand-edit the `data/` folder or delete `clients.db` — that's the agent's memory of your clients.
- ❌ Don't expect it to publish — it makes **drafts** only, on purpose. Nothing goes live until you click Publish yourself.

---

## Who to ask if you're stuck

- **The tool itself** → open an issue on the repo.
- **WordPress login / role problems** → whoever manages that WP site.

Happy uploading! ✨
