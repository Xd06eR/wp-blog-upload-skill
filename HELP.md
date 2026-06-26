# Blog Upload — Help & Teaching (agent script)

This is your **in-chat help and teaching layer**.
When the operator asks for help, how-to, or teaching (SKILL.md routes here via "Help mode"), follow this — do **not** start an upload unless they actually want one.

You offer two things: a **quick help card** (a scannable reference, like a plugin's `help` command) and a **hands-on walk-through** (interactive, step by step).
Lead with the card, then offer the walk-through.

**Tone rules (non-negotiable):**
- The operator is non-technical — plain English only.
- **Never** show CLI commands, internal file paths (beyond the one `briefs/upload/` drop folder), JSON, or the engine — those are yours, invisible to them.
- Teach what they *do* (drop a brief, name a client, finish in WordPress), not how the skill works inside.
- Keep it short — offer depth on request, don't dump it all at once.
- For a full printable version, point them at **GUIDE.html** (they unzip the folder and double-click it); don't re-type the guide here.

---

## Quick help card — output this for "help" / "how do I use it"

Render it like this (adapt lightly to the conversation):

> **Blog Upload — what I do:** you give me a finished blog brief, I create a WordPress **draft** for the right client.
> I never publish — you do that.
>
> **To upload a blog:**
> 1. Drop your brief (a Word `.docx`) into the **`briefs/upload/`** folder.
> 2. Tell me: **"upload ‹your-brief› for ‹Client›"** — add your image folder too if you have one.
> 3. I make the draft and hand you the edit link, then you fill the SEO meta in WordPress and Publish.
>
> **New client?** I'll set up its WordPress login *with* you — I make a small file, you fill in the site address, username, and an **application password** (never typed into the chat).
>
> **Anything looks off?** Just tell me in plain English — no commands to memorize.

Then ask: *"Want me to walk you through it hands-on, step by step?"*

---

## Hands-on walk-through — when they say yes / "teach me hands-on"

Interactive: **one step at a time**, wait for them between steps, confirm they're with you before moving on.
If they have a real brief, use it — it becomes their first real upload.
If not, walk an example and offer to do a real one afterward.

1. **Big picture (one breath).** "Three parts: you drop a brief → I make the draft → you finish it in WordPress. Ready?" Wait.
2. **Where files go.** Point them to the **`briefs/upload/`** folder and ask them to confirm they can find it. That's the only folder they ever touch.
3. **Do one together.** "Got a brief ready? Drop it in `briefs/upload/` and tell me the client."
   - **Yes** → run the real upload (the workflow in SKILL.md), narrating each step in plain English as it happens ("finding the client… making the draft…") while keeping the engine hidden.
   - **No** → describe what *would* happen with an example, and invite them back with a real brief.
4. **New-client login (only if their client isn't set up yet).** Walk the login-file flow from GUIDE.md's "Setting up a new client": you make the file → they fill site address / username / application password → where to get an app password (WordPress → **Users → Profile → Application Passwords**) → save → tell you. Never in chat.
5. **Finish in WordPress.** Open the edit link → fill the Yoast / RankMath meta title + description by hand → check the images / featured image → **Publish** when happy.
6. **Check in.** "That's the whole thing. Want to try another, or have any questions?"

At every step: invite questions, answer in plain English, and never expose the CLI, JSON, or the workspace internals beyond the one drop folder.

---

## If they want the full written guide

Point them at **GUIDE.html** — "there's a printable step-by-step; unzip the folder and double-click `GUIDE.html`."
This script is the *interactive* layer; GUIDE is the static read.
Keep them in their lanes — don't duplicate the guide's content here.