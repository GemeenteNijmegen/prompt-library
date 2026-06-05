"""Tests for POST/GET/DELETE /api/v1/me/api-keys.

API keys are opaque, gallery-issued secrets (ADR 0004 rev 2). Issuance and
revocation are pure DB operations — no Keycloak call is involved — so these
tests run fully offline against the in-memory DB.
"""
from src.models.api_key import ApiKey
from src.services.api_key_service import KEY_PREFIX, hash_token
from tests.conftest import make_jwt


# ---------------------------------------------------------------------------
# POST /api/v1/me/api-keys
# ---------------------------------------------------------------------------

def test_create_api_key_returns_opaque_token_once(client):
    token = make_jwt()
    r = client.post(
        "/api/v1/me/api-keys",
        json={"label": "CI pipeline"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["token"].startswith(KEY_PREFIX)
    assert data["label"] == "CI pipeline"
    assert data["token_prefix"] == data["token"][: len(data["token_prefix"])]
    assert data["expires_at"] is not None
    assert "id" in data
    assert "created_at" in data


def test_create_api_key_stores_only_hash(client, db):
    """The raw secret must never be persisted — only its SHA-256 hash."""
    token = make_jwt(sub="hash-check-user")
    r = client.post(
        "/api/v1/me/api-keys",
        json={"label": "k"},
        headers={"Authorization": f"Bearer {token}"},
    )
    raw = r.json()["data"]["token"]
    key_id = r.json()["data"]["id"]

    row = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    assert row.token_hash == hash_token(raw)
    assert raw not in row.token_hash
    # The full secret is not recoverable from the stored prefix.
    assert len(row.token_prefix) < len(raw)


def test_create_api_key_snapshots_caller_scopes(client, db):
    token = make_jwt(sub="scope-snap-user", scope=["prompt:read", "prompt:write", "apikey:create"])
    r = client.post(
        "/api/v1/me/api-keys",
        json={"label": "scoped"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201
    data = r.json()["data"]
    assert set(data["scopes"]) == {"prompt:read", "prompt:write", "apikey:create"}

    row = db.query(ApiKey).filter(ApiKey.id == data["id"]).first()
    assert set(row.scopes.split()) == {"prompt:read", "prompt:write", "apikey:create"}


def test_create_api_key_token_not_in_list(client):
    """GET after POST must not expose the raw token."""
    token = make_jwt()
    client.post(
        "/api/v1/me/api-keys",
        json={"label": "my key"},
        headers={"Authorization": f"Bearer {token}"},
    )
    r = client.get("/api/v1/me/api-keys", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    for item in r.json()["data"]:
        assert "token" not in item
        assert "token_hash" not in item


def test_create_api_key_writes_audit_event(client, db):
    from src.models.prompt_event import PromptEvent

    token = make_jwt(sub="audit-create-user")
    r = client.post(
        "/api/v1/me/api-keys",
        json={"label": "audit test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201
    key_id = r.json()["data"]["id"]

    event = (
        db.query(PromptEvent)
        .filter(
            PromptEvent.entity_type == "apikey",
            PromptEvent.entity_id == str(key_id),
            PromptEvent.action == "issued",
        )
        .first()
    )
    assert event is not None


def test_create_api_key_blocked_without_scope(client):
    token = make_jwt(scope=["prompt:read"])
    r = client.post(
        "/api/v1/me/api-keys",
        json={"label": "should be blocked"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "FORBIDDEN"


def test_api_key_cannot_mint_another_api_key(client):
    """A leaked key must not be able to spawn fresh credentials."""
    token = make_jwt(sub="self-replicate-user")
    r = client.post(
        "/api/v1/me/api-keys",
        json={"label": "first"},
        headers={"Authorization": f"Bearer {token}"},
    )
    raw = r.json()["data"]["token"]

    r2 = client.post(
        "/api/v1/me/api-keys",
        json={"label": "second via key"},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r2.status_code == 403
    assert r2.json()["detail"]["error"]["code"] == "FORBIDDEN"


# ---------------------------------------------------------------------------
# GET /api/v1/me/api-keys
# ---------------------------------------------------------------------------

def test_list_api_keys_empty(client):
    token = make_jwt(sub="list-test-user")
    r = client.get("/api/v1/me/api-keys", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_list_api_keys_returns_own_keys_only(client):
    token_a = make_jwt(sub="user-a")
    token_b = make_jwt(sub="user-b")

    client.post("/api/v1/me/api-keys", json={"label": "key-a"}, headers={"Authorization": f"Bearer {token_a}"})
    client.post("/api/v1/me/api-keys", json={"label": "key-b"}, headers={"Authorization": f"Bearer {token_b}"})

    r = client.get("/api/v1/me/api-keys", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200
    labels = [k["label"] for k in r.json()["data"]]
    assert "key-a" in labels
    assert "key-b" not in labels


def test_list_api_keys_excludes_revoked(client):
    token = make_jwt(sub="revoke-list-user")

    r_create = client.post(
        "/api/v1/me/api-keys",
        json={"label": "to revoke"},
        headers={"Authorization": f"Bearer {token}"},
    )
    key_id = r_create.json()["data"]["id"]

    client.delete(f"/api/v1/me/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})

    r = client.get("/api/v1/me/api-keys", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    ids = [k["id"] for k in r.json()["data"]]
    assert key_id not in ids


# ---------------------------------------------------------------------------
# DELETE /api/v1/me/api-keys/{id}
# ---------------------------------------------------------------------------

def test_revoke_api_key_marks_revoked_in_db(client, db):
    token = make_jwt(sub="revoke-db-user")

    r_create = client.post(
        "/api/v1/me/api-keys",
        json={"label": "to revoke"},
        headers={"Authorization": f"Bearer {token}"},
    )
    key_id = r_create.json()["data"]["id"]

    r_del = client.delete(f"/api/v1/me/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
    assert r_del.status_code == 204

    row = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    assert row.revoked_at is not None


def test_revoke_api_key_writes_audit_event(client, db):
    from src.models.prompt_event import PromptEvent

    token = make_jwt(sub="revoke-audit-user")

    r_create = client.post(
        "/api/v1/me/api-keys",
        json={"label": "audit revoke"},
        headers={"Authorization": f"Bearer {token}"},
    )
    key_id = r_create.json()["data"]["id"]

    client.delete(f"/api/v1/me/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})

    event = (
        db.query(PromptEvent)
        .filter(
            PromptEvent.entity_type == "apikey",
            PromptEvent.entity_id == str(key_id),
            PromptEvent.action == "revoked",
        )
        .first()
    )
    assert event is not None


def test_revoke_api_key_not_found(client):
    token = make_jwt()
    r = client.delete("/api/v1/me/api-keys/99999", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


def test_revoke_api_key_cross_user_blocked(client):
    """User B cannot revoke User A's key."""
    token_a = make_jwt(sub="cross-user-a")
    token_b = make_jwt(sub="cross-user-b")

    r_create = client.post(
        "/api/v1/me/api-keys",
        json={"label": "a key"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    key_id = r_create.json()["data"]["id"]

    r_del = client.delete(f"/api/v1/me/api-keys/{key_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert r_del.status_code == 404


def test_revoke_api_key_double_revoke_returns_409(client):
    token = make_jwt(sub="double-revoke-user")

    r_create = client.post(
        "/api/v1/me/api-keys",
        json={"label": "double revoke"},
        headers={"Authorization": f"Bearer {token}"},
    )
    key_id = r_create.json()["data"]["id"]

    client.delete(f"/api/v1/me/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
    r2 = client.delete(f"/api/v1/me/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 409
