"""Tests for the remaining read tools added in issue #70.

Tools under test:
  get_prompt(id)        → GET /api/v1/prompts/{id}
  list_featured()       → GET /api/v1/prompts/featured
  list_categories()     → GET /api/v1/categories
  list_tags()           → GET /api/v1/tags

Strategy mirrors test_mcp_search_prompts.py:
  - Set _authorization directly (no HTTP stack needed).
  - Use respx to intercept httpx calls.
  - Core invariant: bearer forwarded unchanged; sidecar adds no auth logic.
"""
import pytest
import respx
import httpx

from gallery_mcp.server import (
    get_prompt,
    list_featured,
    list_categories,
    list_tags,
    _authorization,
    _gallery_auth_failed,
)

BEARER = "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test"
BASE = "http://localhost:8000/api/v1"

PROMPT_DETAIL = {
    "data": {
        "id": 42,
        "title": "Explain code",
        "description": "Explains the given code snippet",
        "prompt_text": "Explain the following code:\n\n{{code}}",
        "example_output": "This function sorts a list…",
        "image_url": None,
        "status": "published_public",
        "visibility": "public",
        "featured": False,
        "view_count": 5,
        "use_count": 1,
        "created_at": "2026-01-01T00:00:00",
        "published_at": "2026-01-02T00:00:00",
        "categories": [],
        "tags": [],
    }
}

FEATURED_RESPONSE = {
    "data": [
        {"id": 1, "title": "Featured prompt", "status": "published_public"}
    ]
}

CATEGORIES_RESPONSE = {
    "data": [
        {"id": 1, "name": "Writing", "slug": "writing", "description": None},
        {"id": 2, "name": "Coding", "slug": "coding", "description": None},
    ]
}

TAGS_RESPONSE = {
    "data": [
        {"id": 1, "name": "python", "slug": "python"},
        {"id": 2, "name": "summarise", "slug": "summarise"},
    ]
}


def _set_auth(value: str | None):
    return _authorization.set(value)


# ── get_prompt ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_prompt_returns_full_detail():
    route = respx.get(f"{BASE}/prompts/42").mock(
        return_value=httpx.Response(200, json=PROMPT_DETAIL)
    )
    token = _set_auth(BEARER)
    try:
        result = await get_prompt(42)
    finally:
        _authorization.reset(token)

    assert route.called
    assert result == PROMPT_DETAIL
    detail = result["data"]
    assert detail["prompt_text"] == "Explain the following code:\n\n{{code}}"
    assert detail["example_output"] == "This function sorts a list…"
    assert "image_url" in detail


@pytest.mark.asyncio
@respx.mock
async def test_get_prompt_bearer_forwarded_unchanged():
    route = respx.get(f"{BASE}/prompts/42").mock(
        return_value=httpx.Response(200, json=PROMPT_DETAIL)
    )
    token = _set_auth(BEARER)
    try:
        await get_prompt(42)
    finally:
        _authorization.reset(token)

    assert route.calls[0].request.headers["authorization"] == BEARER


@pytest.mark.asyncio
@respx.mock
async def test_get_prompt_401_sets_gallery_auth_failed():
    respx.get(f"{BASE}/prompts/42").mock(return_value=httpx.Response(401))
    token = _set_auth(BEARER)
    failed_token = _gallery_auth_failed.set(False)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await get_prompt(42)
        assert _gallery_auth_failed.get() is True
    finally:
        _authorization.reset(token)
        _gallery_auth_failed.reset(failed_token)


@pytest.mark.asyncio
@respx.mock
async def test_get_prompt_404_raises_http_status_error():
    respx.get(f"{BASE}/prompts/99").mock(return_value=httpx.Response(404))
    token = _set_auth(BEARER)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await get_prompt(99)
    finally:
        _authorization.reset(token)


@pytest.mark.asyncio
async def test_get_prompt_missing_auth_raises():
    token = _set_auth(None)
    try:
        with pytest.raises(ValueError, match="Authorization"):
            await get_prompt(1)
    finally:
        _authorization.reset(token)


# ── list_featured ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_list_featured_bearer_forwarded():
    route = respx.get(f"{BASE}/prompts/featured").mock(
        return_value=httpx.Response(200, json=FEATURED_RESPONSE)
    )
    token = _set_auth(BEARER)
    try:
        result = await list_featured()
    finally:
        _authorization.reset(token)

    assert route.called
    assert route.calls[0].request.headers["authorization"] == BEARER
    assert result == FEATURED_RESPONSE


@pytest.mark.asyncio
@respx.mock
async def test_list_featured_401_sets_gallery_auth_failed():
    respx.get(f"{BASE}/prompts/featured").mock(return_value=httpx.Response(401))
    token = _set_auth(BEARER)
    failed_token = _gallery_auth_failed.set(False)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await list_featured()
        assert _gallery_auth_failed.get() is True
    finally:
        _authorization.reset(token)
        _gallery_auth_failed.reset(failed_token)


@pytest.mark.asyncio
async def test_list_featured_missing_auth_raises():
    token = _set_auth(None)
    try:
        with pytest.raises(ValueError, match="Authorization"):
            await list_featured()
    finally:
        _authorization.reset(token)


# ── list_categories ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_list_categories_bearer_forwarded():
    route = respx.get(f"{BASE}/categories").mock(
        return_value=httpx.Response(200, json=CATEGORIES_RESPONSE)
    )
    token = _set_auth(BEARER)
    try:
        result = await list_categories()
    finally:
        _authorization.reset(token)

    assert route.called
    assert route.calls[0].request.headers["authorization"] == BEARER
    assert result == CATEGORIES_RESPONSE


@pytest.mark.asyncio
@respx.mock
async def test_list_categories_401_sets_gallery_auth_failed():
    respx.get(f"{BASE}/categories").mock(return_value=httpx.Response(401))
    token = _set_auth(BEARER)
    failed_token = _gallery_auth_failed.set(False)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await list_categories()
        assert _gallery_auth_failed.get() is True
    finally:
        _authorization.reset(token)
        _gallery_auth_failed.reset(failed_token)


@pytest.mark.asyncio
async def test_list_categories_missing_auth_raises():
    token = _set_auth(None)
    try:
        with pytest.raises(ValueError, match="Authorization"):
            await list_categories()
    finally:
        _authorization.reset(token)


# ── list_tags ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_list_tags_bearer_forwarded():
    route = respx.get(f"{BASE}/tags").mock(
        return_value=httpx.Response(200, json=TAGS_RESPONSE)
    )
    token = _set_auth(BEARER)
    try:
        result = await list_tags()
    finally:
        _authorization.reset(token)

    assert route.called
    assert route.calls[0].request.headers["authorization"] == BEARER
    assert result == TAGS_RESPONSE


@pytest.mark.asyncio
@respx.mock
async def test_list_tags_401_sets_gallery_auth_failed():
    respx.get(f"{BASE}/tags").mock(return_value=httpx.Response(401))
    token = _set_auth(BEARER)
    failed_token = _gallery_auth_failed.set(False)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await list_tags()
        assert _gallery_auth_failed.get() is True
    finally:
        _authorization.reset(token)
        _gallery_auth_failed.reset(failed_token)


@pytest.mark.asyncio
async def test_list_tags_missing_auth_raises():
    token = _set_auth(None)
    try:
        with pytest.raises(ValueError, match="Authorization"):
            await list_tags()
    finally:
        _authorization.reset(token)
