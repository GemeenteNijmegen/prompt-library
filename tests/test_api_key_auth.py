"""Non-mocked tests for authenticating with an opaque API key.

These exercise the full credential path end to end (issue → present the raw key
→ resolve to a user) against the real DB, with no Keycloak mock. They exist
specifically so a design regression in the API-key mechanism cannot hide behind
a mocked Keycloak boundary (the failure mode that hid the offline-token problem
through two "closed" issues — see docs/epics/0001-... history).
"""
from datetime import datetime, timedelta, timezone

from src.models.api_key import ApiKey
from tests.conftest import make_jwt


def _issue_key(client, sub: str, scope=None) -> str:
    token = make_jwt(sub=sub, scope=scope)
    r = client.post(
        "/api/v1/me/api-keys",
        json={"label": "auth-test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201
    return r.json()["data"]["token"]


def test_api_key_authenticates_request(client):
    raw = _issue_key(client, "key-auth-user")
    r = client.get("/api/v1/me", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200
    assert r.json()["data"]["external_id"] == "key-auth-user"


def test_api_key_updates_last_used_at(client, db):
    token = make_jwt(sub="last-used-user")
    r = client.post(
        "/api/v1/me/api-keys",
        json={"label": "lu"},
        headers={"Authorization": f"Bearer {token}"},
    )
    raw = r.json()["data"]["token"]
    key_id = r.json()["data"]["id"]
    assert db.query(ApiKey).filter(ApiKey.id == key_id).first().last_used_at is None

    client.get("/api/v1/me", headers={"Authorization": f"Bearer {raw}"})
    db.expire_all()
    assert db.query(ApiKey).filter(ApiKey.id == key_id).first().last_used_at is not None


def test_revoked_api_key_is_rejected(client):
    token = make_jwt(sub="revoked-auth-user")
    r = client.post(
        "/api/v1/me/api-keys",
        json={"label": "rk"},
        headers={"Authorization": f"Bearer {token}"},
    )
    raw = r.json()["data"]["token"]
    key_id = r.json()["data"]["id"]

    # Works before revocation.
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {raw}"}).status_code == 200

    client.delete(f"/api/v1/me/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})

    rejected = client.get("/api/v1/me", headers={"Authorization": f"Bearer {raw}"})
    assert rejected.status_code == 401


def test_expired_api_key_is_rejected(client, db):
    token = make_jwt(sub="expired-auth-user")
    r = client.post(
        "/api/v1/me/api-keys",
        json={"label": "ek"},
        headers={"Authorization": f"Bearer {token}"},
    )
    raw = r.json()["data"]["token"]
    key_id = r.json()["data"]["id"]

    row = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    db.commit()

    rejected = client.get("/api/v1/me", headers={"Authorization": f"Bearer {raw}"})
    assert rejected.status_code == 401


def test_unknown_api_key_is_rejected(client):
    r = client.get("/api/v1/me", headers={"Authorization": "Bearer pg_not-a-real-key"})
    assert r.status_code == 401


def test_api_key_request_attributed_to_key_in_audit(client, db):
    """A state-changing action via a key must log azp=apikey:<id> for forensics."""
    from src.models.prompt_event import PromptEvent

    token = make_jwt(sub="audit-azp-user")
    # Issue two keys: one to act with, one to revoke with it.
    acting = _issue_key(client, "audit-azp-user")
    acting_id = int(
        db.query(ApiKey).filter(ApiKey.token_prefix == acting[: len("pg_") + 8]).first().id
    )
    r2 = client.post(
        "/api/v1/me/api-keys", json={"label": "victim"},
        headers={"Authorization": f"Bearer {token}"},
    )
    victim_id = r2.json()["data"]["id"]

    # Revoke the victim key using the acting key (DELETE needs only auth).
    r = client.delete(
        f"/api/v1/me/api-keys/{victim_id}", headers={"Authorization": f"Bearer {acting}"}
    )
    assert r.status_code == 204

    event = (
        db.query(PromptEvent)
        .filter(
            PromptEvent.entity_type == "apikey",
            PromptEvent.entity_id == str(victim_id),
            PromptEvent.action == "revoked",
        )
        .first()
    )
    assert event is not None
    assert event.client_id == f"apikey:{acting_id}"
