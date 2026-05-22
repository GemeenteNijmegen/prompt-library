#!/usr/bin/env python3
"""Import prompts from the Leiden AI Challenge API into the local database."""
import argparse
import sys
import urllib.request
import json
from datetime import datetime

sys.path.insert(0, ".")

from src.database import SessionLocal, engine
from src.models import Base
from src.models.prompt import Prompt

SOURCE_URL = "https://leiden-ai-challenge-8af72d90acde.herokuapp.com/api/prompts"

STATUS_MAP = {
    "gepubliceerd": "published",
    "published": "published",
    "draft": "draft",
    "archived": "archived",
}


def fetch_all_prompts() -> list[dict]:
    prompts = []
    page = 1
    while True:
        url = f"{SOURCE_URL}?page={page}"
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read())
        prompts.extend(data["prompts"])
        if page >= data["pages"]:
            break
        page += 1
    return prompts


def import_prompts(user_id: int, dry_run: bool) -> None:
    Base.metadata.create_all(bind=engine)

    print(f"Fetching prompts from {SOURCE_URL} ...")
    remote_prompts = fetch_all_prompts()
    print(f"Found {len(remote_prompts)} prompts.")

    db = SessionLocal()
    try:
        existing_titles = {t for (t,) in db.query(Prompt.title).all()}
        imported = skipped = 0

        for item in remote_prompts:
            title = item["title"]
            if title in existing_titles:
                print(f"  SKIP (exists): {title!r}")
                skipped += 1
                continue

            status = STATUS_MAP.get(item.get("status", ""), "draft")
            created_at = datetime.fromisoformat(item["created_at"]) if item.get("created_at") else None
            published_at = datetime.fromisoformat(item["published_at"]) if item.get("published_at") else None

            prompt = Prompt(
                title=title,
                description=item["description"],
                prompt_text=item["description"],
                status=status,
                visibility="public",
                featured=item.get("featured", False),
                creator_id=user_id,
                view_count=item.get("view_count", 0),
                use_count=item.get("use_count", 0),
                created_at=created_at,
                published_at=published_at,
            )
            if not dry_run:
                db.add(prompt)
            print(f"  IMPORT: {title!r} (status={status})")
            imported += 1

        if not dry_run:
            db.commit()

        print(f"\nDone. imported={imported}, skipped={skipped}" + (" [dry-run, no changes written]" if dry_run else ""))
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import prompts from the Leiden AI Challenge API.")
    parser.add_argument("--user-id", type=int, required=True, help="Local user ID to assign as creator.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and preview without writing to the database.")
    args = parser.parse_args()
    import_prompts(user_id=args.user_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
