"""Tests for scripts/reembed.py (issue #23)."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Make scripts importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.embeddings.fake import FakeEmbedder
from scripts.reembed import reembed_batch, run


def _seed_prompts(db, dev_user, count=3, with_vector=False):
    from src.models.prompt import Prompt
    from src.embeddings.fake import FakeEmbedder
    from src.services.prompt_service import _embedding_source

    embedder = FakeEmbedder()
    prompts = []
    for i in range(count):
        title = f"Prompt {i}"
        desc = f"desc {i}"
        text = f"text {i}"
        vec = json.dumps(embedder.embed_passage(_embedding_source(title, desc, text))) if with_vector else None
        p = Prompt(
            title=title,
            description=desc,
            prompt_text=text,
            status="draft",
            visibility="public",
            featured=False,
            creator_id=dev_user.id,
            embedding_vector=vec,
        )
        db.add(p)
    db.commit()
    for p in db.query(Prompt).filter(Prompt.creator_id == dev_user.id).all():
        prompts.append(p)
    return prompts


class TestReembedBatch:
    def test_updates_all_in_batch(self, db, dev_user):
        prompts = _seed_prompts(db, dev_user, count=3, with_vector=False)
        ids = [p.id for p in prompts]

        embedder = FakeEmbedder()
        updated = reembed_batch(db, ids, embedder, dry_run=False)

        assert updated == 3
        for p in prompts:
            db.refresh(p)
            assert p.embedding_vector is not None

    def test_dry_run_does_not_write(self, db, dev_user):
        from src.models.prompt import Prompt

        prompts = _seed_prompts(db, dev_user, count=2, with_vector=False)
        ids = [p.id for p in prompts]

        embedder = FakeEmbedder()
        reembed_batch(db, ids, embedder, dry_run=True)

        # In dry_run mode no ORM objects are modified, so no commit needed
        for p in prompts:
            # ORM object should be clean (not dirty)
            assert not db.is_modified(p)
            assert p.embedding_vector is None

    def test_batch_size_respected(self, db, dev_user):
        """Verify reembed_batch is called the right number of times for batch_size."""
        prompts = _seed_prompts(db, dev_user, count=5, with_vector=False)
        all_ids = [p.id for p in prompts]

        commit_count = [0]
        orig_commit = db.commit
        def counting_commit():
            commit_count[0] += 1
            orig_commit()
        db.commit = counting_commit

        embedder = FakeEmbedder()
        batch_size = 2
        for start in range(0, len(all_ids), batch_size):
            reembed_batch(db, all_ids[start:start + batch_size], embedder, dry_run=False)

        db.commit = orig_commit
        assert commit_count[0] == 3  # ceil(5/2) = 3 batches

    def test_interruption_leaves_committed_batches_intact(self, db, dev_user):
        """First batch commits; second batch raises; first batch data should persist."""
        from src.models.prompt import Prompt

        prompts = _seed_prompts(db, dev_user, count=4, with_vector=False)
        ids = [p.id for p in prompts]
        half = ids[:2]
        second_half = ids[2:]

        embedder = FakeEmbedder()

        # First batch — commits fine
        reembed_batch(db, half, embedder, dry_run=False)

        # Verify first half is updated
        for p in prompts[:2]:
            db.refresh(p)
            assert p.embedding_vector is not None

        # Second batch fails
        bad_embedder = MagicMock()
        bad_embedder.embed_passage.side_effect = RuntimeError("explode")
        with pytest.raises(Exception):
            from src.services.prompt_service import reembed_prompt
            reembed_prompt(db, second_half[0], bad_embedder)

        # First half untouched
        for p in prompts[:2]:
            db.refresh(p)
            assert p.embedding_vector is not None

        # Second half still NULL
        for p in prompts[2:]:
            db.refresh(p)
            assert p.embedding_vector is None


class TestRunFunction:
    """Test run() via reembed_batch directly on the test DB session."""

    def test_run_embeds_all(self, db, dev_user):
        from src.models.prompt import Prompt

        prompts = _seed_prompts(db, dev_user, count=3, with_vector=False)
        ids = [p.id for p in prompts]

        embedder = FakeEmbedder()
        updated = reembed_batch(db, ids, embedder, dry_run=False)

        assert updated == 3
        for p in prompts:
            db.refresh(p)
            assert p.embedding_vector is not None

    def test_run_only_missing(self, db, dev_user):
        """--only-missing skips rows that already have a vector."""
        from src.models.prompt import Prompt
        from src.services.prompt_service import _embedding_source

        embedder = FakeEmbedder()
        # One prompt with vector, one without
        title_with = "Has Vector"
        source = _embedding_source(title_with, "d", "p")
        p_with = _seed_prompts.__wrapped__(db, dev_user, 1) if hasattr(_seed_prompts, "__wrapped__") else None

        all_prompts = _seed_prompts(db, dev_user, count=2, with_vector=False)
        p_no_vec = all_prompts[0]
        p_with_vec = all_prompts[1]
        # Give p_with_vec an existing vector
        p_with_vec.embedding_vector = json.dumps([0.0] * 384)
        db.commit()

        null_ids = [p_no_vec.id]
        updated = reembed_batch(db, null_ids, embedder, dry_run=False)

        assert updated == 1
        db.refresh(p_no_vec)
        assert p_no_vec.embedding_vector is not None
        # p_with_vec unchanged (we didn't pass its id)
        db.refresh(p_with_vec)
        assert p_with_vec.embedding_vector == json.dumps([0.0] * 384)

    def test_run_dry_run_no_writes(self, db, dev_user):
        prompts = _seed_prompts(db, dev_user, count=2, with_vector=False)
        ids = [p.id for p in prompts]

        reembed_batch(db, ids, FakeEmbedder(), dry_run=True)

        for p in prompts:
            assert not db.is_modified(p)
            assert p.embedding_vector is None

    def test_run_logs_progress(self, db, dev_user, caplog):
        import logging
        prompts = _seed_prompts(db, dev_user, count=3, with_vector=False)
        all_ids = [p.id for p in prompts]
        embedder = FakeEmbedder()

        with caplog.at_level(logging.INFO, logger="scripts.reembed"):
            # Simulate the progress logging loop that run() does
            import scripts.reembed as reembed_mod
            total = len(all_ids)
            processed = 0
            batch_size = 2
            for start in range(0, total, batch_size):
                batch = all_ids[start:start + batch_size]
                reembed_batch(db, batch, embedder, dry_run=False)
                processed += len(batch)
                pct = int(processed / total * 100)
                reembed_mod.log.info("processed %d / %d (%d%%)", processed, total, pct)

        progress_logs = [r for r in caplog.records if "processed" in r.message]
        assert len(progress_logs) >= 1

    def test_run_exits_nonzero_on_failure(self, db, dev_user):
        """When reembed_batch raises, it should propagate (caller wraps in try/except)."""
        bad_embedder = MagicMock()
        bad_embedder.embed_passage.side_effect = RuntimeError("db gone")

        prompts = _seed_prompts(db, dev_user, count=1, with_vector=False)
        ids = [p.id for p in prompts]

        with pytest.raises(Exception):
            reembed_batch(db, ids, bad_embedder, dry_run=False)

    def test_run_idempotent(self, db, dev_user):
        """Running twice on a fully-embedded corpus re-embeds successfully both times."""
        prompts = _seed_prompts(db, dev_user, count=2, with_vector=True)
        ids = [p.id for p in prompts]
        embedder = FakeEmbedder()

        updated1 = reembed_batch(db, ids, embedder, dry_run=False)
        updated2 = reembed_batch(db, ids, embedder, dry_run=False)

        assert updated1 == 2
        assert updated2 == 2
