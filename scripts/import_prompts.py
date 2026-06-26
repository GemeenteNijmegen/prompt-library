#!/usr/bin/env python3
"""Import prompts from the Leiden AI Challenge API into a Prompt Gallery deployment."""
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

SOURCE_URL = "https://leiden-ai-challenge-8af72d90acde.herokuapp.com/api/prompts"

STATUS_MAP = {
    "gepubliceerd": "published_public",
    "published": "published_public",
    "draft": "draft",
    "archived": "archived",
}


def fetch_all_prompts() -> list[dict]:
    ids = []
    page = 1
    while True:
        url = f"{SOURCE_URL}?page={page}"
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read())
        ids.extend(item["id"] for item in data["prompts"])
        if page >= data["pages"]:
            break
        page += 1
    return ids


def fetch_prompt_detail(prompt_id: int) -> dict:
    url = f"{SOURCE_URL}/{prompt_id}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read())


def find_prompt_by_title(api_base: str, token: str, title: str) -> int | None:
    qs = urllib.parse.urlencode({"search": title, "per_page": 100})
    req = urllib.request.Request(
        f"{api_base}/api/v1/prompts?{qs}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
        for p in body.get("data", []):
            if p["title"] == title:
                return p["id"]
    except urllib.error.HTTPError:
        pass
    return None


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


def patch_prompt(api_base: str, token: str, prompt_id: int, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{api_base}/api/v1/prompts/{prompt_id}",
        data=body,
        method="PATCH",
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


def import_prompts(api_base: str, token: str, dry_run: bool, overwrite: bool) -> None:
    print(f"Fetching prompts from {SOURCE_URL} ...")
    prompt_ids = fetch_all_prompts()
    print(f"Found {len(prompt_ids)} prompts.")
    print(f"Destination: {api_base}")

    imported = failed = 0

    for prompt_id in prompt_ids:
        item = fetch_prompt_detail(prompt_id)
        title = item["title"]
        status = STATUS_MAP.get(item.get("status", ""), "draft")
        example_output = item.get("example_output") or None
        image_url = item.get("prompt_image") or None
        tag_names = [t["name"] for t in item.get("tags") or []]

        payload = {
            "title": title,
            "description": item["description"],
            "prompt_text": item["prompt_text"],
            "example_output": example_output,
            "image_url": image_url,
            "status": status,
            "visibility": "public",
            "featured": item.get("featured", False),
            "category_ids": [],
            "tag_names": tag_names,
        }

        if dry_run:
            existing_id = find_prompt_by_title(api_base, token, title) if overwrite else None
            extras = []
            if existing_id:
                extras.append(f"overwrite id={existing_id}")
            if example_output:
                extras.append("example_output")
            if image_url:
                extras.append(f"image_url={image_url}")
            if tag_names:
                extras.append(f"tags={tag_names}")
            extra_str = f" [{', '.join(extras)}]" if extras else ""
            print(f"  DRY-RUN: {title!r} (status={status}){extra_str}")
            imported += 1
            continue

        if overwrite:
            existing_id = find_prompt_by_title(api_base, token, title)
        else:
            existing_id = None

        if existing_id:
            code, body = patch_prompt(api_base, token, existing_id, payload)
            if code == 200:
                print(f"  OVERWRITE: {title!r} (id={existing_id}, status={status})")
                imported += 1
            else:
                msg = body.get("detail", body)
                print(f"  FAIL [{code}]: {title!r} — {msg}", file=sys.stderr)
                failed += 1
        else:
            code, body = post_prompt(api_base, token, payload)
            if code == 201:
                print(f"  IMPORT: {title!r} (status={status})")
                imported += 1
            else:
                msg = body.get("detail", body)
                print(f"  FAIL [{code}]: {title!r} — {msg}", file=sys.stderr)
                failed += 1

    suffix = " [dry-run, no changes written]" if dry_run else ""
    print(f"\nDone. imported={imported}, failed={failed}{suffix}")
    if failed:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import prompts from the Leiden AI Challenge API.")
    parser.add_argument(
        "--api-url",
        default="https://prompts.ai.sandbox-01.csp-nijmegen.nl",
        help="Base URL of the destination Prompt Gallery API.",
    )
    parser.add_argument("--token", required=True, help="Bearer token for the destination API.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and preview without posting.")
    parser.add_argument("--overwrite", action="store_true", help="Update existing prompts matched by title instead of skipping them.")
    args = parser.parse_args()
    import_prompts(api_base=args.api_url, token=args.token, dry_run=args.dry_run, overwrite=args.overwrite)


if __name__ == "__main__":
    main()
