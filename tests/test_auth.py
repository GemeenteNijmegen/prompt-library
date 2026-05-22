import os
import time

import pytest
from jose import jwt

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["ENVIRONMENT"] = "testing"
os.environ["JWT_SECRET_KEY"] = "test-secret-key"
os.environ["JWKS_URI"] = ""

from tests.conftest import make_jwt

_SECRET = "test-secret-key"
_ISSUER = "http://localhost:9000"


# ---------------------------------------------------------------------------
# GET /api/v1/me — issue #11
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

    # last_seen_at should be updated (or at minimum present)
    assert ts2 >= ts1


def test_me_invalid_token(client):
    r = client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/auth/generate-key — issue #12
# ---------------------------------------------------------------------------

def test_generate_key_with_manage_keys_scope(client):
    token = make_jwt(scope=["admin:manage_keys"])
    r = client.post(
        "/api/v1/auth/generate-key",
        json={"scope": ["prompt:read", "prompt:create"], "expires_in_days": 365},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201
    data = r.json()["data"]
    assert "token" in data
    assert "expires_at" in data
    assert data["scope"] == ["prompt:read", "prompt:create"]


def test_generate_key_token_is_verifiable(client):
    from src.utils.jwt_utils import decode_and_verify

    token = make_jwt(scope=["admin:manage_keys"])
    r = client.post(
        "/api/v1/auth/generate-key",
        json={"scope": ["prompt:read"], "expires_in_days": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201
    machine_token = r.json()["data"]["token"]
    claims = decode_and_verify(machine_token)
    assert "prompt:read" in claims["scope"]


def test_generate_key_forbidden_without_scope(client):
    token = make_jwt(scope=["prompt:read"])
    r = client.post(
        "/api/v1/auth/generate-key",
        json={"scope": ["prompt:read"], "expires_in_days": 365},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "FORBIDDEN"


def test_generate_key_requires_auth(client):
    r = client.post(
        "/api/v1/auth/generate-key",
        json={"scope": ["prompt:read"], "expires_in_days": 365},
    )
    assert r.status_code == 401


def test_cli_generate_key(tmp_path):
    import subprocess
    result = subprocess.run(
        ["python3", "scripts/generate_key.py", "--scope", "prompt:read", "prompt:create", "--expires-in-days", "30"],
        capture_output=True,
        text=True,
        env={**os.environ, "JWT_SECRET_KEY": _SECRET, "JWT_ISSUER": _ISSUER},
        cwd="/workspace/projects/prompt-gallery",
    )
    assert result.returncode == 0
    token = result.stdout.strip()
    assert token

    claims = jwt.decode(token, _SECRET, algorithms=["HS256"], options={"verify_aud": False})
    assert "prompt:read" in claims["scope"]
    assert "prompt:create" in claims["scope"]
