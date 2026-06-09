"""Tests for gallery_mcp.server — search_prompts tracer bullet (issue #68).

Strategy:
- Set the _authorization context var directly to simulate a real HTTP request.
- Use respx to mock the httpx call to the gallery, so tests run without a live stack.
- Verify that the bearer token is forwarded unchanged (the core invariant of ADR 0005).
"""
import pytest
import respx
import httpx

from gallery_mcp.server import search_prompts, _authorization

BEARER = "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test"
API_KEY = "pg_abc123"
GALLERY_PROMPTS_URL = "http://localhost:8000/api/v1/prompts"

SAMPLE_RESPONSE = {
    "data": [
        {
            "id": 1,
            "title": "Write a summary",
            "description": "Summarise the given text",
            "status": "published_public",
            "visibility": "public",
            "featured": False,
            "view_count": 10,
            "use_count": 3,
            "created_at": "2026-01-01T00:00:00",
            "published_at": "2026-01-02T00:00:00",
            "categories": [],
            "tags": [],
        }
    ],
    "total": 1,
    "page": 1,
    "per_page": 20,
    "pages": 1,
}


def _set_auth(value: str | None):
    """Helper: set the request-scoped context var as the middleware would."""
    return _authorization.set(value)


# ── Token forwarding — the key invariant ─────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_bearer_token_forwarded_unchanged():
    route = respx.get(GALLERY_PROMPTS_URL).mock(
        return_value=httpx.Response(200, json=SAMPLE_RESPONSE)
    )
    token = _set_auth(BEARER)
    try:
        result = await search_prompts()
    finally:
        _authorization.reset(token)

    assert route.called
    assert route.calls[0].request.headers["authorization"] == BEARER
    assert result == SAMPLE_RESPONSE


@pytest.mark.asyncio
@respx.mock
async def test_api_key_forwarded_unchanged():
    """pg_… opaque API keys go through the same path as JWTs."""
    route = respx.get(GALLERY_PROMPTS_URL).mock(
        return_value=httpx.Response(200, json=SAMPLE_RESPONSE)
    )
    token = _set_auth(f"Bearer {API_KEY}")
    try:
        result = await search_prompts()
    finally:
        _authorization.reset(token)

    assert route.calls[0].request.headers["authorization"] == f"Bearer {API_KEY}"
    assert result == SAMPLE_RESPONSE


# ── Parameter pass-through ────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_query_param_forwarded():
    route = respx.get(GALLERY_PROMPTS_URL).mock(
        return_value=httpx.Response(200, json=SAMPLE_RESPONSE)
    )
    token = _set_auth(BEARER)
    try:
        await search_prompts(query="summarise")
    finally:
        _authorization.reset(token)

    assert "search=summarise" in str(route.calls[0].request.url)


@pytest.mark.asyncio
@respx.mock
async def test_pagination_params_forwarded():
    route = respx.get(GALLERY_PROMPTS_URL).mock(
        return_value=httpx.Response(200, json=SAMPLE_RESPONSE)
    )
    token = _set_auth(BEARER)
    try:
        await search_prompts(page=2, per_page=5)
    finally:
        _authorization.reset(token)

    url = str(route.calls[0].request.url)
    assert "page=2" in url
    assert "per_page=5" in url


@pytest.mark.asyncio
@respx.mock
async def test_category_and_tag_filter_forwarded():
    route = respx.get(GALLERY_PROMPTS_URL).mock(
        return_value=httpx.Response(200, json=SAMPLE_RESPONSE)
    )
    token = _set_auth(BEARER)
    try:
        await search_prompts(category_id=3, tag="python")
    finally:
        _authorization.reset(token)

    url = str(route.calls[0].request.url)
    assert "category_id=3" in url
    assert "tag=python" in url


@pytest.mark.asyncio
@respx.mock
async def test_featured_filter_forwarded():
    route = respx.get(GALLERY_PROMPTS_URL).mock(
        return_value=httpx.Response(200, json=SAMPLE_RESPONSE)
    )
    token = _set_auth(BEARER)
    try:
        await search_prompts(featured=True)
    finally:
        _authorization.reset(token)

    assert "featured=true" in str(route.calls[0].request.url)


# ── Missing auth ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_auth_raises():
    token = _set_auth(None)
    try:
        with pytest.raises(ValueError, match="Authorization"):
            await search_prompts()
    finally:
        _authorization.reset(token)


# ── Gallery error propagation ─────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_gallery_4xx_raises_http_status_error():
    respx.get(GALLERY_PROMPTS_URL).mock(return_value=httpx.Response(401))
    token = _set_auth(BEARER)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await search_prompts()
    finally:
        _authorization.reset(token)


@pytest.mark.asyncio
@respx.mock
async def test_gallery_5xx_raises_http_status_error():
    respx.get(GALLERY_PROMPTS_URL).mock(return_value=httpx.Response(500))
    token = _set_auth(BEARER)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await search_prompts()
    finally:
        _authorization.reset(token)


# ── No auth leakage: sidecar adds nothing ─────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_sidecar_adds_no_extra_auth_headers():
    """The sidecar must not inject any header other than the caller's own."""
    route = respx.get(GALLERY_PROMPTS_URL).mock(
        return_value=httpx.Response(200, json=SAMPLE_RESPONSE)
    )
    token = _set_auth(BEARER)
    try:
        await search_prompts()
    finally:
        _authorization.reset(token)

    headers = dict(route.calls[0].request.headers)
    # The only auth-related header must be the one we forwarded verbatim.
    assert headers["authorization"] == BEARER
    # No extra gallery-side secrets (no X-Internal-Token, no service-account header…)
    extra_auth_keys = [k for k in headers if k.lower() not in {
        "authorization", "host", "accept", "accept-encoding",
        "connection", "user-agent", "content-length",
    }]
    assert extra_auth_keys == [], f"Unexpected headers: {extra_auth_keys}"
