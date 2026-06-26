#!/usr/bin/env python3
"""Interactive wizard to create a new prompt via the Prompt Gallery API."""
import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request


# ── helpers ──────────────────────────────────────────────────────────────────

def ask(label: str, default: str | None = None, required: bool = True) -> str:
    hint = f" [{default}]" if default is not None else ""
    while True:
        value = input(f"  {label}{hint}: ").strip()
        if not value and default is not None:
            return default
        if value or not required:
            return value
        print("  ! This field is required.")


def ask_choice(label: str, choices: list[str], default: str) -> str:
    options = "  /  ".join(
        f"[{c}]" if c == default else c for c in choices
    )
    while True:
        value = input(f"  {label} ({options}): ").strip().lower()
        if not value:
            return default
        if value in choices:
            return value
        print(f"  ! Choose one of: {', '.join(choices)}")


def ask_yn(label: str, default: bool = False) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        value = input(f"  {label} {hint}: ").strip().lower()
        if not value:
            return default
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        print("  ! Enter y or n.")


def ask_multiline(label: str) -> str:
    print(f"  {label}")
    print("  (Enter text; finish with a line containing only 'END' or press Ctrl+D)")
    lines = []
    try:
        while True:
            line = input()
            if line == "END":
                break
            lines.append(line)
    except EOFError:
        pass
    return "\n".join(lines)


def ask_tags() -> list[str]:
    raw = input("  Tags (comma-separated, or leave blank): ").strip()
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def post_prompt(api_base: str, token: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{api_base}/api/v1/prompts",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# ── wizard ────────────────────────────────────────────────────────────────────

def wizard(api_base: str, token: str) -> None:
    print()
    print("  ╔══════════════════════════════════╗")
    print("  ║   Prompt Gallery — New Prompt    ║")
    print("  ╚══════════════════════════════════╝")
    print()

    title       = ask("Title")
    description = ask("Description")
    prompt_text = ask_multiline("Prompt text")
    if not prompt_text.strip():
        print("  ! Prompt text is required.", file=sys.stderr)
        sys.exit(1)

    print()
    example_output = ask("Example output (optional)", default="", required=False) or None
    print()

    status     = ask_choice("Status",     ["draft", "published_org", "published_public", "archived"], "draft")
    visibility = ask_choice("Visibility", ["public", "internal", "restricted"], "public")
    featured   = ask_yn("Featured?", default=False)
    tags       = ask_tags()

    print()
    print("  ── Summary ──────────────────────────────────")
    print(f"  Title       : {title}")
    print(f"  Description : {description}")
    print(f"  Prompt text : {prompt_text[:80].rstrip()}{'…' if len(prompt_text) > 80 else ''}")
    if example_output:
        print(f"  Example out : {example_output[:60]}{'…' if len(example_output) > 60 else ''}")
    print(f"  Status      : {status}")
    print(f"  Visibility  : {visibility}")
    print(f"  Featured    : {featured}")
    print(f"  Tags        : {', '.join(tags) if tags else '(none)'}")
    print(f"  Destination : {api_base}")
    print()

    if not ask_yn("Submit?", default=True):
        print("  Cancelled.")
        return

    payload = {
        "title": title,
        "description": description,
        "prompt_text": prompt_text,
        "status": status,
        "visibility": visibility,
        "featured": featured,
        "category_ids": [],
        "tag_names": tags,
    }
    if example_output:
        payload["example_output"] = example_output

    print()
    print("  Submitting…", end=" ", flush=True)
    code, body = post_prompt(api_base, token, payload)

    if code == 201:
        created = body.get("data", body)
        print(f"done.\n\n  Created prompt id={created.get('id')} — {created.get('title')!r}")
    elif code == 409:
        print("failed.\n\n  Error: a prompt with that title already exists.", file=sys.stderr)
        sys.exit(1)
    else:
        msg = body.get("detail", body)
        print(f"failed.\n\n  Error [{code}]: {msg}", file=sys.stderr)
        sys.exit(1)


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive wizard to create a prompt.")
    parser.add_argument(
        "--api-url",
        default="https://prompts.ai.sandbox-01.csp-nijmegen.nl",
        help="Base URL of the Prompt Gallery API.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Bearer token (prompted securely if omitted).",
    )
    args = parser.parse_args()

    token = args.token or getpass.getpass("  Bearer token: ")
    if not token:
        print("Error: a bearer token is required.", file=sys.stderr)
        sys.exit(1)

    try:
        wizard(api_base=args.api_url, token=token)
    except KeyboardInterrupt:
        print("\n  Cancelled.")
        sys.exit(0)


if __name__ == "__main__":
    main()
