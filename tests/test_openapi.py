"""Tests for CORS configuration and OpenAPI spec."""
import json
from pathlib import Path

import pytest

OPENAPI_PATH = Path(__file__).parent.parent / "openapi" / "openapi.json"

EXPECTED_PATHS = [
    "/api/v1/health",
    "/api/v1/prompts",
    "/api/v1/prompts/featured",
    "/api/v1/categories",
    "/api/v1/tags",
    "/api/v1/uploads/images",
]


def test_openapi_json_is_valid_json():
    assert OPENAPI_PATH.exists(), "openapi/openapi.json not found — run the export script"
    content = OPENAPI_PATH.read_text()
    spec = json.loads(content)
    assert isinstance(spec, dict)


def test_openapi_json_contains_expected_paths():
    spec = json.loads(OPENAPI_PATH.read_text())
    paths = spec.get("paths", {})
    for expected in EXPECTED_PATHS:
        assert expected in paths, f"Path {expected!r} not found in OpenAPI spec"


def test_cors_allowed_origin_header_present(client):
    resp = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code in (200, 204)
    assert "access-control-allow-origin" in resp.headers


def test_cors_disallowed_origin_not_echoed(client):
    resp = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    acao = resp.headers.get("access-control-allow-origin", "")
    assert "evil.example.com" not in acao
