#!/usr/bin/env python3
"""Re-embed all non-deleted prompts using the currently-configured embedder.

Run after switching EMBEDDING_MODEL or to backfill prompts created before the
embedding feature shipped.

Usage:
    python scripts/reembed.py [--only-missing] [--batch-size N] [--dry-run]
"""
import argparse
import logging
import os
import sys
from pathlib import Path

# Load .env if present (mirror generate_key.py)
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


def reembed_batch(session, prompt_ids: list[int], embedder, dry_run: bool) -> int:
    """Re-embed a list of prompt IDs. Returns count updated (or would-update in dry_run)."""
    from src.models.prompt import Prompt
    from src.services.prompt_service import _embedding_source
    import json

    updated = 0
    for pid in prompt_ids:
        p = session.query(Prompt).filter(Prompt.id == pid, Prompt.deleted_at.is_(None)).first()
        if p is None:
            continue
        source = _embedding_source(p.title, p.description, p.prompt_text)
        vector = embedder.embed_passage(source)
        if not dry_run:
            p.embedding_vector = json.dumps(vector)
        updated += 1

    if not dry_run:
        session.commit()

    return updated


def run(
    only_missing: bool = False,
    batch_size: int = 100,
    dry_run: bool = False,
) -> int:
    """Main re-embed loop. Returns 0 on success, 1 on failure."""
    from src.database import SessionLocal
    from src.models.prompt import Prompt
    from src.embeddings import get_embedder

    embedder = get_embedder()
    log.info("Using embedder: %s", type(embedder).__name__)

    if dry_run:
        log.info("DRY RUN — no rows will be modified")

    db = SessionLocal()
    try:
        q = db.query(Prompt.id).filter(Prompt.deleted_at.is_(None))
        if only_missing:
            q = q.filter(Prompt.embedding_vector.is_(None))
        q = q.order_by(Prompt.id)
        all_ids: list[int] = [row[0] for row in q.all()]
    finally:
        db.close()

    total = len(all_ids)
    log.info("Found %d prompts to process", total)

    processed = 0
    for batch_start in range(0, total, batch_size):
        batch_ids = all_ids[batch_start: batch_start + batch_size]
        batch_db = SessionLocal()
        try:
            updated = reembed_batch(batch_db, batch_ids, embedder, dry_run)
        except Exception:
            log.exception("Batch starting at %d failed — rolling back", batch_start)
            batch_db.rollback()
            return 1
        finally:
            batch_db.close()

        processed += len(batch_ids)
        pct = int(processed / total * 100) if total else 100
        log.info("processed %d / %d (%d%%)", processed, total, pct)

    log.info("Done. %s", "No changes written (dry run)." if dry_run else "All batches committed.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-embed all prompts in-place")
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Re-embed only rows where embedding_vector IS NULL",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        metavar="N",
        help="Number of prompts per DB transaction (default: 100)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be done without writing",
    )
    args = parser.parse_args()

    sys.exit(run(
        only_missing=args.only_missing,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
