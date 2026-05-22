"""Tests for in-memory caching on hot-read endpoints."""
import json
from unittest.mock import MagicMock, patch

import pytest

import src.cache as cache_mod
from tests.conftest import make_jwt


@pytest.fixture(autouse=True)
def clear_cache():
    cache_mod.cache_clear()
    yield
    cache_mod.cache_clear()


def test_categories_list_cached_on_second_call(client, sample_category, auth_headers):
    resp1 = client.get("/api/v1/categories")
    assert resp1.status_code == 200

    # Poison the underlying cache entry directly to verify second call uses cache
    cache_mod.cache_set("categories:list", ["__cached__"])

    resp2 = client.get("/api/v1/categories")
    assert resp2.status_code == 200
    assert resp2.json()["data"] == ["__cached__"]


def test_categories_cache_invalidated_after_create(client, auth_headers):
    # Prime the cache
    client.get("/api/v1/categories")
    cache_mod.cache_set("categories:list", ["__stale__"])

    # Create a new category (requires admin:manage_taxonomy)
    resp = client.post(
        "/api/v1/categories",
        json={"name": "NewCat", "description": "desc"},
        headers=auth_headers,
    )
    assert resp.status_code == 201

    # Cache should have been cleared — live data returned
    cached = cache_mod.cache_get("categories:list")
    assert cached is None


def test_tags_list_cached_on_second_call(client, sample_tag):
    resp1 = client.get("/api/v1/tags")
    assert resp1.status_code == 200

    cache_mod.cache_set("tags:list", ["__cached_tag__"])

    resp2 = client.get("/api/v1/tags")
    assert resp2.json()["data"] == ["__cached_tag__"]


def test_tags_cache_invalidated_after_create(client, auth_headers):
    client.get("/api/v1/tags")
    cache_mod.cache_set("tags:list", ["__stale__"])

    resp = client.post("/api/v1/tags", json={"name": "new-tag"}, headers=auth_headers)
    assert resp.status_code == 201

    assert cache_mod.cache_get("tags:list") is None


def test_featured_prompts_cached_on_second_call(client):
    resp1 = client.get("/api/v1/prompts/featured")
    assert resp1.status_code == 200

    cache_mod.cache_set("prompts:featured:anon", ["__cached_featured__"])

    resp2 = client.get("/api/v1/prompts/featured")
    assert resp2.json()["data"] == ["__cached_featured__"]


def test_featured_prompts_cache_invalidated_after_create(client, auth_headers, sample_category):
    client.get("/api/v1/prompts/featured")
    cache_mod.cache_set("prompts:featured:anon", ["__stale__"])
    cache_mod.cache_set("prompts:featured:auth", ["__stale__"])

    resp = client.post(
        "/api/v1/prompts",
        json={
            "title": "New Prompt",
            "description": "desc",
            "prompt_text": "Do {thing}",
            "status": "draft",
            "visibility": "public",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201

    assert cache_mod.cache_get("prompts:featured:anon") is None
    assert cache_mod.cache_get("prompts:featured:auth") is None


def test_redis_cache_get_and_set():
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps({"key": "value"})

    with patch("src.cache.settings") as mock_settings, \
         patch("src.cache._redis_client", return_value=mock_redis):
        mock_settings.REDIS_URL = "redis://localhost:6379"

        result = cache_mod.cache_get("test-key")
        mock_redis.get.assert_called_once_with("test-key")
        assert result == {"key": "value"}


def test_redis_cache_set():
    mock_redis = MagicMock()

    with patch("src.cache.settings") as mock_settings, \
         patch("src.cache._redis_client", return_value=mock_redis):
        mock_settings.REDIS_URL = "redis://localhost:6379"

        cache_mod.cache_set("test-key", {"data": 42}, ttl=30)
        mock_redis.setex.assert_called_once_with("test-key", 30, json.dumps({"data": 42}))
