import os
import time

import pytest
from jose import jwt

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["ENVIRONMENT"] = "testing"
os.environ["JWT_SECRET_KEY"] = "test-secret-key"
os.environ["JWKS_URI"] = ""

from tests.conftest import make_jwt, TEST_ORG_ID, TEST_AZP

_SECRET = "test-secret-key"
_ISSUER = "http://localhost:9000"


# ---------------------------------------------------------------------------
# GET /api/v1/me
# ---------------------------------------------------------------------------

def test_me_authenticated(client):
    token = make_jwt(name="Alice", email="alice@example.com")
    r = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["external_id"] == "dev-user-001"
    assert data["name"] == "Alice"
    assert data["email"] == "alice@example.com"
    assert "id" in data
    assert "last_seen_at" in data


def test_me_unauthenticated(client):
    r = client.get("/api/v1/me")
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["code"] == "UNAUTHORIZED"


def test_me_expired_token(client):
    token = make_jwt(expired=True)
    r = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["detail"]["error"]["code"] == "UNAUTHORIZED"


def test_me_last_seen_at_updated(client):
    token = make_jwt()
    r1 = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert r1.status_code == 200
    ts1 = r1.json()["data"]["last_seen_at"]

    time.sleep(0.01)

    r2 = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    ts2 = r2.json()["data"]["last_seen_at"]

    assert ts2 >= ts1


def test_me_invalid_token(client):
    r = client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_me_upserts_org_id(client):
    """Auth middleware persists org_id from JWT into the users table."""
    token = make_jwt(org_id=TEST_ORG_ID)
    r = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200

    from src.models.user import User
    from tests.conftest import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.external_id == "dev-user-001").first()
        assert user is not None
        assert user.org_id == TEST_ORG_ID
    finally:
        db.close()


def test_generate_key_endpoint_removed(client):
    """Ensure the old HS256 signing endpoint is gone (epic §9)."""
    r = client.post(
        "/api/v1/auth/generate-key",
        json={"scope": ["prompt:read"], "expires_in_days": 365},
        headers={"Authorization": f"Bearer {make_jwt()}"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Scope resolution — token format variants
# ---------------------------------------------------------------------------

def _token_with_claims(extra: dict) -> str:
    """Mint a minimal HS256 token with the given extra claims."""
    now = int(time.time())
    payload = {
        "sub": "scope-test-user",
        "aud": "prompt-gallery-api",
        "iss": _ISSUER,
        "iat": now - 10,
        "exp": now + 3600,
        **extra,
    }
    return jwt.encode(payload, _SECRET, algorithm="HS256")


def test_scope_array_grants_access(client):
    """A token carrying ``scope`` as a JSON array (dev/OAuth2 format) should be honoured."""
    token = _token_with_claims({
        "scope": ["prompt:read", "prompt:write", "prompt:create"],
        "org_id": TEST_ORG_ID,
        "azp": TEST_AZP,
        "name": "Scope Test",
        "email": "scope@test.local",
    })
    r = client.post(
        "/api/v1/prompts",
        json={"title": "t", "description": "d", "prompt_text": "p"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text


def test_scope_string_grants_access(client):
    """A token carrying ``scope`` as a space-separated string (RFC 9068) should be honoured."""
    token = _token_with_claims({
        "scope": "prompt:read prompt:write prompt:create",
        "org_id": TEST_ORG_ID,
        "azp": TEST_AZP,
        "name": "Scope Test",
        "email": "scope@test.local",
    })
    r = client.post(
        "/api/v1/prompts",
        json={"title": "t", "description": "d", "prompt_text": "p"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text


def test_realm_access_roles_takes_precedence_over_scope_string(client):
    """When realm_access.roles is present it wins; the scope string is ignored
    so OIDC scopes (openid, profile) do not bleed into permission checks."""
    token = _token_with_claims({
        # realm_access has the real permissions
        "realm_access": {"roles": ["prompt:read", "prompt:write", "prompt:create"]},
        # scope string carries only OIDC scopes — must NOT grant prompt:create on its own
        "scope": "openid profile email",
        "org_id": TEST_ORG_ID,
        "azp": TEST_AZP,
        "name": "Scope Test",
        "email": "scope@test.local",
    })
    r = client.post(
        "/api/v1/prompts",
        json={"title": "t", "description": "d", "prompt_text": "p"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text


def test_missing_scope_returns_403(client):
    """A token with no create scope is rejected."""
    token = _token_with_claims({
        "scope": ["prompt:read"],
        "org_id": TEST_ORG_ID,
        "azp": TEST_AZP,
        "name": "Scope Test",
        "email": "scope@test.local",
    })
    r = client.post(
        "/api/v1/prompts",
        json={"title": "t", "description": "d", "prompt_text": "p"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
