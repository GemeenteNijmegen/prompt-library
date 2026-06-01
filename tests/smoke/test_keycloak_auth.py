"""Tracer-bullet smoke tests: real RS256 token accepted; stale HS256 rejected.

Requires a running Keycloak + gallery-api stack. See tests/smoke/conftest.py.
"""
import time

import pytest
from jose import jwt as jose_jwt

from tests.smoke.conftest import skip_if_no_stack


@pytest.mark.smoke
@skip_if_no_stack
def test_rs256_token_accepted(api_url: str, rs256_token: str):
    """A real RS256 token issued by local Keycloak must reach a protected endpoint."""
    import httpx

    resp = httpx.get(
        f"{api_url}/api/v1/me",
        headers={"Authorization": f"Bearer {rs256_token}"},
        timeout=10.0,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "data" in data or "id" in data or "sub" in data or "email" in data


@pytest.mark.smoke
@skip_if_no_stack
def test_hs256_token_rejected_when_jwks_uri_set(api_url: str):
    """When the gallery API is configured with JWKS_URI, HS256 tokens must be rejected."""
    stale_token = jose_jwt.encode(
        {
            "sub": "attacker-001",
            "iss": "http://localhost:9000",
            "aud": "prompt-gallery-api",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
            "scope": ["prompt:read"],
        },
        "any-secret-key",
        algorithm="HS256",
    )

    import httpx

    resp = httpx.get(
        f"{api_url}/api/v1/me",
        headers={"Authorization": f"Bearer {stale_token}"},
        timeout=10.0,
    )
    assert resp.status_code == 401, (
        f"HS256 token should be rejected (401) when JWKS_URI is active, "
        f"but got {resp.status_code}: {resp.text}"
    )


@pytest.mark.smoke
@skip_if_no_stack
def test_rs256_user_token_accepted(api_url: str, rs256_user_token: str):
    """A password-grant RS256 token for the dev user must also be accepted."""
    import httpx

    resp = httpx.get(
        f"{api_url}/api/v1/me",
        headers={"Authorization": f"Bearer {rs256_user_token}"},
        timeout=10.0,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
