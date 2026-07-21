"""Tests for DNS rebinding protection configuration (issue #98).

build_app() must add the netloc of MCP_RESOURCE_URL to FastMCP's allowed_hosts
and allowed_origins so that production traffic reaches the handler.  Unknown
external hosts/origins must be denied (421 / 403 respectively).

Two layers:
1. Configuration — verify build_app() sets the right settings on the mcp object.
2. Middleware — verify TransportSecurityMiddleware allows/denies as expected.
   (Full HTTP stack tests would require running the ASGI lifespan to initialise
   the session manager's task group, which is out of scope for a unit test.)
"""
import pytest
from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings
from starlette.requests import Request

from gallery_mcp.server import build_app, mcp
from gallery_mcp import config

TEST_RESOURCE_URL = "http://mcp.test"
TEST_RESOURCE_HOST = "mcp.test"
TEST_RESOURCE_ORIGIN = "http://mcp.test"


@pytest.fixture
def built_app(monkeypatch):
    monkeypatch.setattr(config.settings, "MCP_RESOURCE_URL", TEST_RESOURCE_URL)
    return build_app()


# ── Configuration ─────────────────────────────────────────────────────────────


def test_resource_host_added_to_allowlist(built_app):
    """build_app() must add the resource host to transport_security.allowed_hosts."""
    assert TEST_RESOURCE_HOST in mcp.settings.transport_security.allowed_hosts


def test_localhost_retained_in_allowlist(built_app):
    """localhost:* must remain in the allowlist so dev / CI keeps working."""
    assert "localhost:*" in mcp.settings.transport_security.allowed_hosts


def test_loopback_ip_retained_in_allowlist(built_app):
    """127.0.0.1:* must remain in the allowlist."""
    assert "127.0.0.1:*" in mcp.settings.transport_security.allowed_hosts


def test_dns_rebinding_protection_stays_enabled(built_app):
    """Protection must stay enabled — not merely present with an empty list."""
    assert mcp.settings.transport_security.enable_dns_rebinding_protection is True


def test_resource_origin_added_to_allowed_origins(built_app):
    """build_app() must add the resource origin to transport_security.allowed_origins."""
    assert TEST_RESOURCE_ORIGIN in mcp.settings.transport_security.allowed_origins


def test_localhost_origin_in_allowed_origins(built_app):
    """http://localhost:* must be in allowed_origins for browser-based MCP clients."""
    assert "http://localhost:*" in mcp.settings.transport_security.allowed_origins


# ── Middleware behaviour ───────────────────────────────────────────────────────


def _make_request(
    host: str,
    content_type: str = "application/json",
    origin: str | None = None,
) -> Request:
    headers = [(b"host", host.encode()), (b"content-type", content_type.encode())]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    return Request({"type": "http", "method": "POST", "headers": headers})


def _middleware_for(resource_host: str, resource_origin: str) -> TransportSecurityMiddleware:
    return TransportSecurityMiddleware(
        TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", resource_host],
            allowed_origins=[
                "http://localhost:*",
                "http://127.0.0.1:*",
                "https://localhost:*",
                resource_origin,
            ],
        )
    )


def _middleware() -> TransportSecurityMiddleware:
    return _middleware_for(TEST_RESOURCE_HOST, TEST_RESOURCE_ORIGIN)


# Host validation

@pytest.mark.asyncio
async def test_resource_host_passes_middleware():
    """Host matching the resource host must pass (validate_request returns None)."""
    result = await _middleware().validate_request(
        _make_request(TEST_RESOURCE_HOST), is_post=True
    )
    assert result is None


@pytest.mark.asyncio
async def test_unknown_external_host_rejected_with_421():
    """An unrecognised external host must be rejected with HTTP 421."""
    result = await _middleware().validate_request(
        _make_request("evil.example.com"), is_post=True
    )
    assert result is not None
    assert result.status_code == 421


@pytest.mark.asyncio
async def test_localhost_with_port_passes_middleware():
    """localhost:PORT matches the localhost:* wildcard (the real pattern in use)."""
    result = await _middleware().validate_request(
        _make_request("localhost:8001"), is_post=True
    )
    assert result is None


@pytest.mark.asyncio
async def test_loopback_ip_with_port_passes_middleware():
    """127.0.0.1:PORT matches the 127.0.0.1:* wildcard."""
    result = await _middleware().validate_request(
        _make_request("127.0.0.1:8001"), is_post=True
    )
    assert result is None


# Origin validation

@pytest.mark.asyncio
async def test_no_origin_passes():
    """Non-browser clients (Claude Desktop, mcp-remote) send no Origin — must pass."""
    result = await _middleware().validate_request(
        _make_request(TEST_RESOURCE_HOST), is_post=True
    )
    assert result is None


@pytest.mark.asyncio
async def test_localhost_origin_passes():
    """MCP Inspector runs at http://localhost:PORT — that Origin must be accepted."""
    result = await _middleware().validate_request(
        _make_request(TEST_RESOURCE_HOST, origin="http://localhost:6274"), is_post=True
    )
    assert result is None


@pytest.mark.asyncio
async def test_resource_origin_passes():
    """Requests from the resource URL's own origin must be accepted."""
    result = await _middleware().validate_request(
        _make_request(TEST_RESOURCE_HOST, origin=TEST_RESOURCE_ORIGIN), is_post=True
    )
    assert result is None


@pytest.mark.asyncio
async def test_unknown_origin_rejected_with_403():
    """An unrecognised external Origin must be rejected with HTTP 403."""
    result = await _middleware().validate_request(
        _make_request(TEST_RESOURCE_HOST, origin="https://evil.example.com"), is_post=True
    )
    assert result is not None
    assert result.status_code == 403
