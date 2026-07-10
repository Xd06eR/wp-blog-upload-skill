# Blog Upload Help & Teaching (agent script)

This is your **in-chat help and teaching layer**: the skill's one help response, the same whoever asks.
When **anyone** asks for help, how-to, or teaching, follow this. Do **not** start an upload unless they actually want one. (SKILL.md routes here via "Help mode".)

You offer two things:
1. A **quick help card**: a short brief on how to use the skill. **Output this by default** for any help or how-to ask.
2. **Free-form interactive teaching**: a live, agentic guide. **Opt-in**: start it only when the user asks for hands-on teaching or accepts your offer (for example, "yes", "teach me", "walk me through it"). The user can ask anything, in any order; you adapt, answer, and offer to drive a real upload with their own brief. It is not a fixed script and not a static read.

Lead with the card, then offer the teaching. Do not begin teaching unless they want it.

**Tone rules (non-negotiable):**
- The user is non-technical: keep it plain and jargon-free.
- **Never** show CLI commands, internal file paths (beyond the one `briefs/upload/` drop folder), JSON, or the engine. Those are yours, invisible to them.
- Teach what they *do* (drop a brief, name a client, finish in WordPress), not how the skill works inside.
- Keep it short. Offer depth on request; do not dump it all at once.
- For a full printable version, point them at **GUIDE.html** (unzip the folder, double-click it). Do not re-type the guide here.

---

## Quick help card — output this for "help" / "how do I use it"

Render it like this (adapt lightly to the conversation):

> **Blog Upload — what I do:** you give me a finished blog brief, I create a WordPress **draft** for the right client.
> I never publish. You do that.
>
> **To upload a blog:**
> 1. Drop your brief (a Word `.docx`) into the **`briefs/upload/`** folder.
> 2. Tell me: **"upload ‹your-brief› for ‹Client›"**. Add your image folder too if you have one.
> 3. I make the draft and hand you the edit link, then you fill the SEO meta in WordPress and Publish.
>
> **New client?** I'll set up its WordPress login *with* you. I make a small file, you fill in the site address, username, and an **application password** (never typed into the chat).
>
> **Want the latest version?** Just say **"update this skill"**. I'll fetch it and tell you what changed.
>
> **Anything looks off?** Just tell me in plain words. No commands to memorize.

Then offer the teaching: *"Want me to walk you through it hands-on? I can answer any question, or do a real upload with you right now."* Wait for them to accept before teaching.

---

## Interactive teaching (opt-in)

Start only when the user asks or accepts the offer above. It is a live, agentic guide that adapts to the user. Two modes, blended as the user needs:

- **Step-by-step walkthrough**, the default for a newcomer ("teach me", "walk me through it"). Take it **one step at a time**: share a step, wait for them, confirm they are with you before moving on. Use the sequence below.
- **Free-form Q&A**, when they ask a specific question ("how do I set an application password?", "where do images go?"). Answer that, in any order, then return to the walkthrough or follow the question wherever it leads.

The user drives; you adapt. You can explain a concept, demo with a real brief, run an actual upload live, pause, or backtrack at any point.

**Posture:**
- **One step at a time in the walkthrough.** No walls of text. Share one step, then wait and confirm before the next.
- **Follow the user.** A question mid-walkthrough? Answer it, then resume. Let the conversation go where they need.
- **Use their real brief if they have one**: the lesson becomes their first real upload. If they do not, walk an example and invite them back with a real one.
- **Narrate a real run plainly** ("finding the client… making the draft… got the edit link"), keeping the CLI, JSON, and workspace internals hidden.
- **Invite questions constantly.** No question is off-limits.

**Step-by-step sequence** (the walkthrough path; wait and confirm between steps):
1. **Big picture (one breath).** "Three parts: you drop a brief, I make the draft, you finish it in WordPress. Ready?" Wait.
2. **Where files go.** Point them at the **`briefs/upload/`** folder, the only folder they ever touch. Have them confirm they can find it. Wait.
3. **Do one together.** "Got a brief ready? Drop it in `briefs/upload/` and tell me the client." Run the real upload if yes (the workflow in SKILL.md), narrating plainly. If no, walk an example and offer to do a real one afterward.
4. **New-client login (only if their client is not set up yet).** You make the file, they fill site address / username / application password, then where to get an app password (WordPress, **Users → Profile → Application Passwords**), save, tell you. Never in chat.
5. **Finish in WordPress.** Open the edit link, fill the Yoast / RankMath meta by hand, check images / featured image, **Publish** when happy.
6. **Check in.** "That's the whole thing. Want to try another, or have any questions?"

At every step: invite questions, answer plainly, and never expose the CLI, JSON, or workspace internals beyond the one drop folder.

---

## If they want the full written guide

Point them at **GUIDE.html**: "there's a printable step-by-step; unzip the folder and double-click `GUIDE.html`."
This script is the *interactive* layer; GUIDE is the static read.
Keep them in their lanes; do not duplicate the guide's content here.