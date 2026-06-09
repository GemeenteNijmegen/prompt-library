"""Tests for MCP OAuth protected-resource discovery and 401 translation (issue #69).

Three groups:
1. GET /.well-known/oauth-protected-resource — RFC 9728 metadata (full ASGI stack).
2. Missing auth → HTTP 401 + WWW-Authenticate (full ASGI stack; middleware intercepts
   before FastMCP so no lifespan needed).
3. Gallery 401 → HTTP 401 translation — tested in two layers:
   a. Tool layer: search_prompts sets _gallery_auth_failed when gallery returns 401.
   b. Middleware layer: _AuthMiddleware converts the flag into HTTP 401 + WWW-Authenticate
      using a lightweight mock inner app (avoids FastMCP lifespan).
"""
import pytest
import respx
import httpx

from gallery_mcp.server import build_app, _AuthMiddleware, _gallery_auth_failed, _authorization, search_prompts
from gallery_mcp import config

BEARER = "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test"
GALLERY_PROMPTS_URL = "http://localhost:8000/api/v1/prompts"
SAMPLE_RESPONSE = {"data": [], "total": 0, "page": 1, "per_page": 20, "pages": 0}

# MCP streamable-HTTP headers required by the protocol
MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

TOOL_CALL_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {"name": "search_prompts", "arguments": {}},
}

TEST_RESOURCE_URL = "http://mcp.test"
TEST_REALM_URL = "http://keycloak.test/realms/nijmegen"
EXPECTED_METADATA_URL = f"{TEST_RESOURCE_URL}/.well-known/oauth-protected-resource"


@pytest.fixture
def mcp_app(monkeypatch):
    monkeypatch.setattr(config.settings, "MCP_RESOURCE_URL", TEST_RESOURCE_URL)
    monkeypatch.setattr(config.settings, "KEYCLOAK_REALM_URL", TEST_REALM_URL)
    return build_app()


# ── /.well-known/oauth-protected-resource ────────────────────────────────────


@pytest.mark.asyncio
async def test_well_known_status_200(mcp_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_app), base_url="http://testserver"
    ) as client:
        response = await client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_well_known_content_type_json(mcp_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_app), base_url="http://testserver"
    ) as client:
        response = await client.get("/.well-known/oauth-protected-resource")
    assert "application/json" in response.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_well_known_resource_field(mcp_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_app), base_url="http://testserver"
    ) as client:
        response = await client.get("/.well-known/oauth-protected-resource")
    assert response.json()["resource"] == TEST_RESOURCE_URL


@pytest.mark.asyncio
async def test_well_known_authorization_servers(mcp_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_app), base_url="http://testserver"
    ) as client:
        response = await client.get("/.well-known/oauth-protected-resource")
    assert TEST_REALM_URL in response.json()["authorization_servers"]


@pytest.mark.asyncio
async def test_well_known_bearer_methods(mcp_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_app), base_url="http://testserver"
    ) as client:
        response = await client.get("/.well-known/oauth-protected-resource")
    assert "header" in response.json()["bearer_methods_supported"]


# ── No auth → 401 + WWW-Authenticate (middleware intercepts before FastMCP) ──


@pytest.mark.asyncio
async def test_no_auth_returns_401(mcp_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_app), base_url="http://testserver"
    ) as client:
        response = await client.post("/mcp", json=TOOL_CALL_BODY, headers=MCP_HEADERS)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_no_auth_www_authenticate_present(mcp_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_app), base_url="http://testserver"
    ) as client:
        response = await client.post("/mcp", json=TOOL_CALL_BODY, headers=MCP_HEADERS)
    assert "www-authenticate" in response.headers


@pytest.mark.asyncio
async def test_no_auth_www_authenticate_shape(mcp_app):
    """WWW-Authenticate must be Bearer with a resource_metadata pointer."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_app), base_url="http://testserver"
    ) as client:
        response = await client.post("/mcp", json=TOOL_CALL_BODY, headers=MCP_HEADERS)
    www = response.headers["www-authenticate"]
    assert www.startswith("Bearer")
    assert "resource_metadata" in www
    assert EXPECTED_METADATA_URL in www


# ── Public paths need no auth ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_no_auth_required(mcp_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_app), base_url="http://testserver"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_well_known_no_auth_required(mcp_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_app), base_url="http://testserver"
    ) as client:
        response = await client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200


# ── Tool layer: gallery 401 sets the _gallery_auth_failed flag ────────────────


@pytest.mark.asyncio
@respx.mock
async def test_gallery_401_sets_auth_failed_flag():
    """search_prompts must set _gallery_auth_failed when gallery responds 401."""
    respx.get(GALLERY_PROMPTS_URL).mock(return_value=httpx.Response(401))
    auth_tok = _authorization.set(BEARER)
    failed_tok = _gallery_auth_failed.set(False)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await search_prompts()
        assert _gallery_auth_failed.get() is True
    finally:
        _authorization.reset(auth_tok)
        _gallery_auth_failed.reset(failed_tok)


@pytest.mark.asyncio
@respx.mock
async def test_gallery_500_does_not_set_auth_failed_flag():
    """Only gallery 401 triggers the flag — 500 must leave it False."""
    respx.get(GALLERY_PROMPTS_URL).mock(return_value=httpx.Response(500))
    auth_tok = _authorization.set(BEARER)
    failed_tok = _gallery_auth_failed.set(False)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await search_prompts()
        assert _gallery_auth_failed.get() is False
    finally:
        _authorization.reset(auth_tok)
        _gallery_auth_failed.reset(failed_tok)


# ── Middleware layer: _gallery_auth_failed flag → HTTP 401 + WWW-Authenticate ─
# Uses a lightweight mock inner app to avoid FastMCP lifespan setup.


def _make_mock_scope(auth: str | None = None, path: str = "/mcp") -> dict:
    headers = [(b"authorization", auth.encode())] if auth else []
    return {"type": "http", "path": path, "headers": headers}


async def _noop_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def _capture_send(received: list):
    async def _send(message) -> None:
        received.append(message)
    return _send


@pytest.mark.asyncio
async def test_middleware_flag_translates_to_401(monkeypatch):
    monkeypatch.setattr(config.settings, "MCP_RESOURCE_URL", TEST_RESOURCE_URL)

    async def inner_app(scope, receive, send):
        _gallery_auth_failed.set(True)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}", "more_body": False})

    middleware = _AuthMiddleware(inner_app)
    received: list = []
    await middleware(_make_mock_scope(auth=BEARER), _noop_receive, _capture_send(received))
    start = next(m for m in received if m["type"] == "http.response.start")
    assert start["status"] == 401


@pytest.mark.asyncio
async def test_middleware_flag_adds_www_authenticate(monkeypatch):
    monkeypatch.setattr(config.settings, "MCP_RESOURCE_URL", TEST_RESOURCE_URL)

    async def inner_app(scope, receive, send):
        _gallery_auth_failed.set(True)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}", "more_body": False})

    middleware = _AuthMiddleware(inner_app)
    received: list = []
    await middleware(_make_mock_scope(auth=BEARER), _noop_receive, _capture_send(received))
    start = next(m for m in received if m["type"] == "http.response.start")
    headers = dict(start["headers"])
    www = headers.get(b"www-authenticate", b"").decode()
    assert www.startswith("Bearer")
    assert "resource_metadata" in www
    assert EXPECTED_METADATA_URL in www


@pytest.mark.asyncio
async def test_middleware_no_flag_keeps_200(monkeypatch):
    """When _gallery_auth_failed stays False, the original status is preserved."""
    monkeypatch.setattr(config.settings, "MCP_RESOURCE_URL", TEST_RESOURCE_URL)

    async def inner_app(scope, receive, send):
        # flag is NOT set — simulates a successful gallery call
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}", "more_body": False})

    middleware = _AuthMiddleware(inner_app)
    received: list = []
    await middleware(_make_mock_scope(auth=BEARER), _noop_receive, _capture_send(received))
    start = next(m for m in received if m["type"] == "http.response.start")
    assert start["status"] == 200
