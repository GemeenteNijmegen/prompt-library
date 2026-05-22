"""Tests for conditional re-embed on PATCH (issue #22)."""
import json
from unittest.mock import MagicMock, patch

import pytest

from src.embeddings.fake import FakeEmbedder


def _make_prompt(db, dev_user, title="T", description="D", prompt_text="P"):
    from src.models.prompt import Prompt
    from src.embeddings.fake import FakeEmbedder
    from src.services.prompt_service import _embedding_source

    embedder = FakeEmbedder()
    source = _embedding_source(title, description, prompt_text)
    vec = embedder.embed_passage(source)

    p = Prompt(
        title=title,
        description=description,
        prompt_text=prompt_text,
        status="draft",
        visibility="public",
        featured=False,
        creator_id=dev_user.id,
        embedding_vector=json.dumps(vec),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


class TestPatchReembed:
    def test_patch_title_triggers_reembed(self, client, auth_headers, db, dev_user):
        p = _make_prompt(db, dev_user, title="Old Title")
        old_vec = p.embedding_vector

        r = client.patch(f"/api/v1/prompts/{p.id}", json={"title": "New Title"}, headers=auth_headers)
        assert r.status_code == 200

        db.refresh(p)
        assert p.embedding_vector != old_vec

    def test_patch_description_triggers_reembed(self, client, auth_headers, db, dev_user):
        p = _make_prompt(db, dev_user, description="Old desc")
        old_vec = p.embedding_vector

        r = client.patch(f"/api/v1/prompts/{p.id}", json={"description": "New desc"}, headers=auth_headers)
        assert r.status_code == 200

        db.refresh(p)
        assert p.embedding_vector != old_vec

    def test_patch_prompt_text_triggers_reembed(self, client, auth_headers, db, dev_user):
        p = _make_prompt(db, dev_user, prompt_text="Old text")
        old_vec = p.embedding_vector

        r = client.patch(f"/api/v1/prompts/{p.id}", json={"prompt_text": "New text"}, headers=auth_headers)
        assert r.status_code == 200

        db.refresh(p)
        assert p.embedding_vector != old_vec

    def test_patch_featured_does_not_reembed(self, client, auth_headers, db, dev_user):
        p = _make_prompt(db, dev_user)
        old_vec = p.embedding_vector

        r = client.patch(f"/api/v1/prompts/{p.id}", json={"featured": True}, headers=auth_headers)
        assert r.status_code == 200

        db.refresh(p)
        assert p.embedding_vector == old_vec

    def test_patch_visibility_does_not_reembed(self, client, auth_headers, db, dev_user):
        p = _make_prompt(db, dev_user)
        old_vec = p.embedding_vector

        r = client.patch(f"/api/v1/prompts/{p.id}", json={"visibility": "internal"}, headers=auth_headers)
        assert r.status_code == 200

        db.refresh(p)
        assert p.embedding_vector == old_vec

    def test_patch_image_url_does_not_reembed(self, client, auth_headers, db, dev_user):
        p = _make_prompt(db, dev_user)
        old_vec = p.embedding_vector

        r = client.patch(f"/api/v1/prompts/{p.id}", json={"image_url": "https://example.com/img.png"}, headers=auth_headers)
        assert r.status_code == 200

        db.refresh(p)
        assert p.embedding_vector == old_vec

    def test_patch_example_output_does_not_reembed(self, client, auth_headers, db, dev_user):
        p = _make_prompt(db, dev_user)
        old_vec = p.embedding_vector

        r = client.patch(f"/api/v1/prompts/{p.id}", json={"example_output": "some output"}, headers=auth_headers)
        assert r.status_code == 200

        db.refresh(p)
        assert p.embedding_vector == old_vec

    def test_patch_same_title_no_reembed(self, client, auth_headers, db, dev_user):
        """Sending same title value should not trigger re-embed."""
        p = _make_prompt(db, dev_user, title="Same Title")
        old_vec = p.embedding_vector

        r = client.patch(f"/api/v1/prompts/{p.id}", json={"title": "Same Title"}, headers=auth_headers)
        assert r.status_code == 200

        db.refresh(p)
        assert p.embedding_vector == old_vec

    def test_patch_title_and_featured_one_reembed(self, client, auth_headers, db, dev_user):
        """Combined text+non-text change triggers exactly one reembed."""
        p = _make_prompt(db, dev_user, title="Original")
        old_vec = p.embedding_vector

        embed_call_count = [0]
        real_embedder = FakeEmbedder()
        mock_embedder = MagicMock(wraps=real_embedder)

        def counting_embed(text):
            embed_call_count[0] += 1
            return real_embedder.embed_passage(text)

        mock_embedder.embed_passage.side_effect = counting_embed

        with patch("src.services.prompt_service._get_embedder", return_value=mock_embedder):
            r = client.patch(
                f"/api/v1/prompts/{p.id}",
                json={"title": "Updated Title", "featured": True},
                headers=auth_headers,
            )

        assert r.status_code == 200
        assert embed_call_count[0] == 1

        db.refresh(p)
        assert p.embedding_vector != old_vec

    def test_patch_embed_failure_row_unchanged(self, client, auth_headers, db, dev_user):
        """If embedder raises during PATCH, the row must not be modified."""
        p = _make_prompt(db, dev_user, title="Before Fail")
        old_title = p.title
        old_vec = p.embedding_vector

        with patch("src.services.prompt_service._get_embedder") as mock_emb:
            mock_embedder = MagicMock()
            mock_embedder.embed_passage.side_effect = RuntimeError("embed failure")
            mock_emb.return_value = mock_embedder

            r = client.patch(
                f"/api/v1/prompts/{p.id}",
                json={"title": "After Fail"},
                headers=auth_headers,
            )

        assert r.status_code == 500

        db.expire(p)
        db.refresh(p)
        assert p.title == old_title
        assert p.embedding_vector == old_vec

    def test_cache_invalidated_after_reembed_patch(self, client, auth_headers, db, dev_user):
        import time
        from src.services import prompt_service

        p = _make_prompt(db, dev_user, title="Cache Test")
        prompt_service._vector_cache = {p.id: __import__("numpy").zeros(384)}
        prompt_service._vector_cache_loaded_at = time.monotonic()

        r = client.patch(f"/api/v1/prompts/{p.id}", json={"title": "Cache Bust Title"}, headers=auth_headers)
        assert r.status_code == 200
        assert prompt_service._vector_cache_loaded_at == 0.0

    def test_cache_not_invalidated_when_no_reembed(self, client, auth_headers, db, dev_user):
        import time
        from src.services import prompt_service
        import numpy as np

        p = _make_prompt(db, dev_user)
        stamp = time.monotonic()
        prompt_service._vector_cache = {p.id: np.zeros(384)}
        prompt_service._vector_cache_loaded_at = stamp

        r = client.patch(f"/api/v1/prompts/{p.id}", json={"featured": True}, headers=auth_headers)
        assert r.status_code == 200
        assert prompt_service._vector_cache_loaded_at == stamp
