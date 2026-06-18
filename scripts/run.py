"""CLI entry point -- subcommand-based interface.

Pure stdlib. No agent loop here: the AI agent (Claude Code session)
drives the workflow described in SKILL.md and invokes this CLI for the
deterministic bits (parse, render, POST to WP).

Subcommands:
    init-workspace    Create the workspace skeleton (~/blog-upload-workspace)
    show-workspace    Print the resolved workspace path + state
    list-clients      Print registered client slugs (JSON, for the agent)
    onboard           Register a new client from a JSON credentials file
    list-briefs       Pre-scan a markdown brief for embedded client sections
    inspect-brief     Dump every table + heading found in a brief (debug aid
                      when list-briefs returns empty / strict parser fails)
    upload            Upload one brief from a .md file as a WP draft
    upload-prepared   Upload from an agent-emitted JSON payload (bypasses
                      the markdown parser entirely)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .tools import onboarding, workspace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.run")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("init-workspace", help="Create the workspace folder skeleton if missing.")
    sub.add_parser("show-workspace", help="Print the resolved workspace path + state.")
    sub.add_parser("list-clients", help="Print every registered client (JSON).")
    sub.add_parser("playbook-index",
                   help="Print the always-load playbook index (one record per client: summary + aliases).")

    p_onboard = sub.add_parser("onboard", help="Register a new client from a credentials JSON.")
    p_onboard.add_argument("--from-file", required=True,
                           help="Path to credentials JSON (matches data/secrets/.env.example). Deleted on success.")

    p_briefs = sub.add_parser("list-briefs",
                              help="Pre-scan a markdown brief for embedded client sections (JSON).")
    p_briefs.add_argument("--doc", required=True, help="Path to .md brief.")

    p_inspect = sub.add_parser("inspect-brief",
                               help="Dump every table + heading found in a brief (debug aid for alien formats).")
    p_inspect.add_argument("--doc", required=True, help="Path to .md brief.")

    p_upload = sub.add_parser("upload", help="Upload one brief as a WP draft (commits immediately).")
    p_upload.add_argument("--client", required=True, help="Client slug.")
    p_upload.add_argument("--doc", required=True, help="Path to .md brief.")
    p_upload.add_argument("--brand", default=None,
                          help="Section name inside a multi-brief markdown file (case insensitive).")

    p_prepared = sub.add_parser("upload-prepared",
                                help="Upload from a pre-parsed JSON payload (agent-emitted ParsedDoc).")
    p_prepared.add_argument("--client", required=True, help="Client slug.")
    p_prepared.add_argument("--from-file", required=True,
                            help="Path to JSON payload (shape documented in REFERENCE.md).")

    args = parser.parse_args(argv)

    if not args.cmd:
        parser.print_help()
        return 2

    if args.cmd == "init-workspace":
        return _run_init_workspace()
    if args.cmd == "show-workspace":
        return _run_show_workspace()
    if args.cmd == "list-clients":
        return _run_list_clients()
    if args.cmd == "playbook-index":
        return _run_playbook_index()
    if args.cmd == "onboard":
        return _run_onboard(args)
    if args.cmd == "list-briefs":
        return _run_list_briefs(args)
    if args.cmd == "inspect-brief":
        return _run_inspect_brief(args)
    if args.cmd == "upload":
        return _run_upload(args)
    if args.cmd == "upload-prepared":
        return _run_upload_prepared(args)

    parser.print_help()
    return 2


def _run_init_workspace() -> int:
    workspace.ensure()
    info = workspace.describe()
    print(f"Workspace ready at: {info['root']}")
    print(f"  data/          -> {info['data_dir']}")
    print(f"  briefs/upload/ -> {info['briefs_dir']}")
    print(f"  data/secrets/.env.example created (credentials template).")
    return 0


def _run_show_workspace() -> int:
    print(json.dumps(workspace.describe(), indent=2))
    return 0


def _run_list_clients() -> int:
    # Read-only: resolve an existing workspace, never create one.
    if workspace.find() is None:
        print(json.dumps([], indent=2))
        return 0
    from .tools.client_store import get_store
    store = get_store()
    rows = []
    for slug in store.list_clients():
        cfg = store.get(slug)
        if cfg:
            rows.append({
                "slug": slug,
                "display_name": cfg.display_name,
                "wp_base_url": cfg.wp_base_url,
                "editor": cfg.editor,
            })
    print(json.dumps(rows, indent=2))
    return 0


def _run_playbook_index() -> int:
    # Read-only: resolve an existing workspace, never create one (a missing
    # workspace just means an empty index).
    if workspace.find() is None:
        print(json.dumps([], indent=2))
        return 0
    from .tools.playbook import build_index
    print(json.dumps(build_index(), indent=2))
    return 0


def _run_onboard(args) -> int:
    workspace.ensure()
    src = Path(args.from_file).resolve()
    if not src.exists():
        print(f"ERROR: credentials file not found: {src}", file=sys.stderr)
        return 2

    try:
        creds = _load_creds_json(src)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"ERROR: could not parse {src.name}: {e}", file=sys.stderr)
        return 2

    site_url = creds.get("site_url", "").strip()
    username = creds.get("username", "").strip()
    app_password = creds.get("app_password", "").strip()

    placeholder_tokens = {"your-client-site", "your.wp.username", "xxxx"}
    combined = site_url + username + app_password
    if not all([site_url, username, app_password]) or any(tok in combined for tok in placeholder_tokens):
        print(
            f"ERROR: {src.name} still contains placeholder values. "
            "Edit it with real WP credentials before re-running.",
            file=sys.stderr,
        )
        return 2

    slug = onboarding.derive_slug(site_url)
    print(f"Onboarding '{slug}' from {src.name} ...")

    try:
        result = onboarding.register_client(
            slug=slug,
            site_url=site_url,
            username=username,
            app_password=app_password,
            by="cli_from_file",
        )
    except Exception as e:
        print(f"ERROR: onboarding failed -- {e}", file=sys.stderr)
        return 1

    try:
        src.unlink()
        print(f"  Consumed {src.name} (deleted to prevent credential lingering).")
    except OSError as e:
        print(f"  WARNING: could not delete {src.name}: {e}", file=sys.stderr)
        print("  Delete it manually -- it contains the real app password.", file=sys.stderr)

    print(
        f"\n[OK] Registered client '{result.slug}'\n"
        f"  Site:            {site_url}\n"
        f"  Detected editor: {result.detected_editor}\n"
        f"  Credentials:     {result.credentials_path} (chmod 600)\n"
    )
    return 0


def _run_list_briefs(args) -> int:
    from .tools import parse_md
    from .tools.intake import parser_for
    doc_path = Path(args.doc).expanduser().resolve()
    if not doc_path.exists():
        print(f"ERROR: brief not found: {doc_path}", file=sys.stderr)
        return 2
    try:
        briefs = parser_for(doc_path).list_briefs(doc_path)
    except parse_md.ParseError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(json.dumps([asdict(b) for b in briefs], indent=2))
    return 0


def _run_inspect_brief(args) -> int:
    from .tools import parse_md
    doc_path = Path(args.doc).expanduser().resolve()
    if not doc_path.exists():
        print(f"ERROR: brief not found: {doc_path}", file=sys.stderr)
        return 2
    if doc_path.suffix.lower() == ".docx":
        print(
            "ERROR: inspect-brief is a markdown debug aid. .docx briefs are parsed "
            "natively -- run list-briefs / upload directly on the .docx.",
            file=sys.stderr,
        )
        return 2
    try:
        info = parse_md.inspect(doc_path)
    except parse_md.ParseError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(json.dumps(info, indent=2))
    return 0


def _run_upload(args) -> int:
    workspace.ensure()
    from .upload_blog import upload_blog
    from .tools.client_store import get_store
    from .tools import parse_md

    doc_path = Path(args.doc).expanduser().resolve()
    if not doc_path.exists():
        print(f"ERROR: brief not found: {doc_path}", file=sys.stderr)
        return 2

    cfg = get_store().get(args.client)
    if cfg is None:
        print(
            f"ERROR: unknown client '{args.client}'. "
            f"Onboard this client first (see SKILL.md Phase 1).",
            file=sys.stderr,
        )
        return 2

    try:
        result = upload_blog(doc_path=doc_path, client_cfg=cfg, brand=args.brand)
    except parse_md.ParseError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: upload failed -- {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(json.dumps({
        "title": result.title,
        "post_id": result.post_id,
        "post_url": result.post_url,
        "edit_url": result.edit_url,
        "brand": result.brand,
        "warnings": result.warnings,
    }, indent=2))
    return 0


def _run_upload_prepared(args) -> int:
    workspace.ensure()
    from .upload_blog import upload_prepared
    from .tools.client_store import get_store

    cfg = get_store().get(args.client)
    if cfg is None:
        print(
            f"ERROR: unknown client '{args.client}'. "
            f"Onboard this client first (see SKILL.md Phase 1).",
            file=sys.stderr,
        )
        return 2

    src = Path(args.from_file).expanduser().resolve()
    if not src.exists():
        print(f"ERROR: payload file not found: {src}", file=sys.stderr)
        return 2

    try:
        payload = json.loads(src.read_text())
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON in {src.name}: {e}", file=sys.stderr)
        return 2

    try:
        result = upload_prepared(payload, cfg)
    except ValueError as e:
        print(f"ERROR: invalid payload -- {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"ERROR: upload failed -- {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(json.dumps({
        "title": result.title,
        "post_id": result.post_id,
        "post_url": result.post_url,
        "edit_url": result.edit_url,
        "brand": result.brand,
        "warnings": result.warnings,
    }, indent=2))
    return 0


def _load_creds_json(path: Path) -> dict:
    """Read a credentials JSON. Strips // line comments so the template can ship with notes."""
    raw = path.read_text()
    cleaned = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("//"))
    cleaned = cleaned.strip()
    if not cleaned:
        raise ValueError("file is empty after stripping comments")
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object at the top level")
    return data


if __name__ == "__main__":
    sys.exit(main())
