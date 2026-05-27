"""Tests for the embeddings module (issue #20 and #21)."""
import json
import math
import time
import os
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.embeddings.base import Embedder
from src.embeddings.fake import FakeEmbedder


# ── FakeEmbedder ─────────────────────────────────────────────────────────────

class TestFakeEmbedder:
    def test_dimension(self):
        e = FakeEmbedder()
        assert e.dimension == 384

    def test_embed_passage_returns_correct_length(self):
        e = FakeEmbedder()
        vec = e.embed_passage("hello world")
        assert len(vec) == 384

    def test_embed_query_returns_correct_length(self):
        e = FakeEmbedder()
        vec = e.embed_query("hello world")
        assert len(vec) == 384

    def test_deterministic_same_input(self):
        e = FakeEmbedder()
        v1 = e.embed_passage("foo bar")
        v2 = e.embed_passage("foo bar")
        assert v1 == v2

    def test_unit_vector(self):
        e = FakeEmbedder()
        vec = np.array(e.embed_passage("test text"), dtype=np.float32)
        norm = np.linalg.norm(vec)
        assert abs(norm - 1.0) < 1e-5

    def test_different_inputs_produce_different_vectors(self):
        e = FakeEmbedder()
        v1 = e.embed_passage("hello")
        v2 = e.embed_passage("world")
        assert v1 != v2

    def test_query_and_passage_differ(self):
        e = FakeEmbedder()
        vq = e.embed_query("test")
        vp = e.embed_passage("test")
        assert vq != vp

    def test_implements_embedder_protocol(self):
        e = FakeEmbedder()
        assert isinstance(e, Embedder)


# ── get_embedder factory ─────────────────────────────────────────────────────

class TestGetEmbedder:
    def test_returns_fake_when_flag_set(self):
        from src import config as cfg
        original = cfg.settings.EMBEDDING_USE_FAKE
        cfg.settings.EMBEDDING_USE_FAKE = True
        try:
            from src.embeddings import get_embedder
            e = get_embedder()
            assert isinstance(e, FakeEmbedder)
        finally:
            cfg.settings.EMBEDDING_USE_FAKE = original

    def test_fake_embedder_set_in_tests(self):
        # The conftest sets EMBEDDING_USE_FAKE=true
        from src.embeddings import get_embedder
        e = get_embedder()
        assert isinstance(e, FakeEmbedder)


# ── FastembedEmbedder ─────────────────────────────────────────────────────────

class TestFastembedEmbedder:
    def test_prefix_applied_for_e5_model(self):
        from src.embeddings.fastembed_embedder import FastembedEmbedder

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.ones(384, dtype=np.float32)])

        # multilingual-e5-large is in the prefix map
        embedder = FastembedEmbedder("intfloat/multilingual-e5-large")
        embedder._model = mock_model

        embedder.embed_query("hond")
        call_args = mock_model.embed.call_args[0][0]
        assert call_args[0] == "query: hond"

        mock_model.embed.return_value = iter([np.ones(384, dtype=np.float32)])
        embedder.embed_passage("hond")
        call_args = mock_model.embed.call_args[0][0]
        assert call_args[0] == "passage: hond"

    def test_no_prefix_for_default_model(self):
        """Default model (MiniLM) is symmetric — no query/passage prefix."""
        from src.embeddings.fastembed_embedder import FastembedEmbedder

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.ones(384, dtype=np.float32)])

        embedder = FastembedEmbedder("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        embedder._model = mock_model

        embedder.embed_query("hond")
        call_args = mock_model.embed.call_args[0][0]
        assert call_args[0] == "hond"

        mock_model.embed.return_value = iter([np.ones(384, dtype=np.float32)])
        embedder.embed_passage("hond")
        call_args = mock_model.embed.call_args[0][0]
        assert call_args[0] == "hond"

    def test_no_prefix_for_unknown_model(self):
        from src.embeddings.fastembed_embedder import FastembedEmbedder

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.ones(384, dtype=np.float32)])

        embedder = FastembedEmbedder("some/unknown-model")
        embedder._model = mock_model

        embedder.embed_query("test")
        call_args = mock_model.embed.call_args[0][0]
        assert call_args[0] == "test"

    def test_lazy_load(self):
        from src.embeddings.fastembed_embedder import FastembedEmbedder
        e = FastembedEmbedder()
        assert e._model is None


# ── Embed on create (integration) ────────────────────────────────────────────

class TestEmbedOnCreate:
    def test_vector_stored_after_create(self, client, auth_headers):
        from src.models.prompt import Prompt
        from tests.conftest import engine
        from sqlalchemy.orm import Session

        r = client.post("/api/v1/prompts", json={
            "title": "Embedding Test",
            "description": "Testing embedding on create",
            "prompt_text": "A prompt about {topic}",
        }, headers=auth_headers)
        assert r.status_code == 201
        pid = r.json()["data"]["id"]

        with Session(engine) as s:
            p = s.query(Prompt).filter(Prompt.id == pid).first()
            assert p.embedding_vector is not None
            vec = json.loads(p.embedding_vector)
            assert len(vec) == 384

    def test_embed_failure_blocks_write(self, client, auth_headers, db):
        from src.models.prompt import Prompt

        before_count = db.query(Prompt).count()

        with patch("src.services.prompt_service._get_embedder") as mock_emb:
            mock_embedder = MagicMock()
            mock_embedder.embed_passage.side_effect = RuntimeError("embed exploded")
            mock_emb.return_value = mock_embedder

            r = client.post("/api/v1/prompts", json={
                "title": "Fail Prompt",
                "description": "This should fail",
                "prompt_text": "Some text",
            }, headers=auth_headers)

        assert r.status_code == 500
        after_count = db.query(Prompt).count()
        assert after_count == before_count


# ── Hybrid search ────────────────────────────────────────────────────────────

class TestHybridSearch:
    def _create_prompt(self, client, auth_headers, title, description, prompt_text):
        r = client.post("/api/v1/prompts", json={
            "title": title,
            "description": description,
            "prompt_text": prompt_text,
            "status": "published_org",
            "visibility": "public",
        }, headers=auth_headers)
        assert r.status_code == 201
        return r.json()["data"]["id"]

    def test_search_returns_results(self, client, auth_headers):
        self._create_prompt(client, auth_headers, "Python Guide", "A guide to Python", "Write Python code")
        # Use auth so same-org published_org prompts are visible
        r = client.get("/api/v1/prompts?search=Python", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["meta"]["total"] >= 1

    def test_null_vector_prompt_still_findable_via_keyword(self, client, auth_headers, db, dev_user):
        """Prompts with NULL embedding_vector are findable via keyword search."""
        from src.models.prompt import Prompt
        p = Prompt(
            title="Unique Keyword Prompt",
            description="desc",
            prompt_text="text",
            status="published_public",
            visibility="public",
            featured=False,
            creator_id=dev_user.id,
            embedding_vector=None,
        )
        db.add(p)
        db.commit()

        r = client.get("/api/v1/prompts?search=Unique+Keyword+Prompt")
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["data"]]
        assert p.id in ids

    def test_no_search_unchanged_behavior(self, client, auth_headers):
        """Without search param, no vector code runs and existing behavior holds."""
        r = client.get("/api/v1/prompts")
        assert r.status_code == 200
        body = r.json()
        assert "data" in body
        assert "meta" in body

    def test_visibility_enforced_in_search(self, client, auth_headers, db, dev_user):
        """Anonymous callers cannot see internal/restricted prompts even via search."""
        from src.models.prompt import Prompt
        p = Prompt(
            title="Secret Internal Prompt",
            description="top secret",
            prompt_text="internal only",
            status="published_org",
            visibility="restricted",
            featured=False,
            creator_id=dev_user.id,
        )
        db.add(p)
        db.commit()

        # Anonymous search should not surface the restricted prompt
        r = client.get("/api/v1/prompts?search=Secret+Internal")
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["data"]]
        assert p.id not in ids


# ── Vector cache ─────────────────────────────────────────────────────────────

class TestVectorCache:
    def test_cache_invalidated_after_create(self, client, auth_headers):
        from src.services import prompt_service
        prompt_service._vector_cache = {999: np.zeros(384)}
        prompt_service._vector_cache_loaded_at = time.monotonic()

        client.post("/api/v1/prompts", json={
            "title": "Cache Bust",
            "description": "desc",
            "prompt_text": "text",
        }, headers=auth_headers)

        assert prompt_service._vector_cache_loaded_at == 0.0

    def test_cache_reloads_after_ttl(self, db, dev_user):
        from src.services import prompt_service
        from src.models.prompt import Prompt

        p = Prompt(
            title="TTL Test",
            description="desc",
            prompt_text="text",
            status="published_org",
            visibility="public",
            featured=False,
            creator_id=dev_user.id,
            embedding_vector=json.dumps([0.1] * 384),
        )
        db.add(p)
        db.commit()

        # Load cache with expired timestamp
        prompt_service._vector_cache = {}
        prompt_service._vector_cache_loaded_at = time.monotonic() - 999  # expired

        cache = prompt_service._load_vector_cache(db)
        assert p.id in cache

    def test_cache_not_requeried_within_ttl(self, db, dev_user):
        from src.services import prompt_service
        from src.models.prompt import Prompt
        from unittest.mock import patch

        # Seed a prompt with a vector
        p = Prompt(
            title="Cache Hit",
            description="desc",
            prompt_text="text",
            status="published_org",
            visibility="public",
            featured=False,
            creator_id=dev_user.id,
            embedding_vector=json.dumps([0.1] * 384),
        )
        db.add(p)
        db.commit()

        # First load populates cache
        prompt_service._load_vector_cache(db)
        assert prompt_service._vector_cache_loaded_at > 0

        # Patch query to detect if it runs again
        with patch.object(db, "query", wraps=db.query) as mock_query:
            prompt_service._load_vector_cache(db)
            # Should not have re-queried
            mock_query.assert_not_called()
