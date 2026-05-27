"""Tests for POST /api/v1/me/logout-everywhere."""
import pytest
from unittest.mock import MagicMock, call

from starlette.testclient import TestClient

from tests.conftest import make_jwt
from src.services.keycloak_client import get_keycloak_client, KeycloakError


_FAKE_SESSION_ID = "kc-session-abc"
_FAKE_OFFLINE_TOKEN = "eyJ_fake_offline_token"


def _mock_kc(
    issue_return=None,
    logout_side_effect=None,
    revoke_side_effect=None,
):
    kc = MagicMock()
    kc.issue_offline_token.return_value = (
        issue_return or (_FAKE_OFFLINE_TOKEN, _FAKE_SESSION_ID)
    )
    if logout_side_effect:
        kc.logout_all_sessions.side_effect = logout_side_effect
    if revoke_side_effect:
        kc.revoke_session.side_effect = revoke_side_effect
    return kc


def _make_app(db, kc):
    from src.main import create_app
    from src.dependencies import get_db

    app = create_app()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_keycloak_client] = lambda: kc
    return app


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

def test_logout_everywhere_returns_204_no_keys(db):
    kc = _mock_kc()
    app = _make_app(db, kc)
    token = make_jwt(sub="logout-no-keys-user")
    with TestClient(app, raise_server_exceptions=True) as c:
        r = c.post("/api/v1/me/logout-everywhere", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 204
    kc.logout_all_sessions.assert_called_once()


def test_logout_everywhere_calls_logout_all_sessions_with_external_id(db):
    kc = _mock_kc()
    app = _make_app(db, kc)
    token = make_jwt(sub="some-keycloak-uuid")
    with TestClient(app, raise_server_exceptions=True) as c:
        c.post("/api/v1/me/logout-everywhere", headers={"Authorization": f"Bearer {token}"})
    kc.logout_all_sessions.assert_called_once_with("some-keycloak-uuid")


def test_logout_everywhere_revokes_all_active_api_keys(db):
    kc = _mock_kc()
    app = _make_app(db, kc)
    token = make_jwt(sub="logout-with-keys-user")

    with TestClient(app, raise_server_exceptions=True) as c:
        # Issue two API keys
        c.post("/api/v1/me/api-keys", json={"label": "key1"}, headers={"Authorization": f"Bearer {token}"})
        c.post("/api/v1/me/api-keys", json={"label": "key2"}, headers={"Authorization": f"Bearer {token}"})
        kc.reset_mock()

        r = c.post("/api/v1/me/logout-everywhere", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 204
    # revoke_session called once per key
    assert kc.revoke_session.call_count == 2
    kc.revoke_session.assert_any_call(_FAKE_SESSION_ID)


def test_logout_everywhere_marks_api_keys_revoked_in_db(db):
    from src.models.api_key import ApiKey

    kc = _mock_kc()
    app = _make_app(db, kc)
    token = make_jwt(sub="logout-db-check-user")

    with TestClient(app, raise_server_exceptions=True) as c:
        r_key = c.post("/api/v1/me/api-keys", json={"label": "k"}, headers={"Authorization": f"Bearer {token}"})
        key_id = r_key.json()["data"]["id"]
        kc.reset_mock()

        r = c.post("/api/v1/me/logout-everywhere", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 204
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    assert key.revoked_at is not None


def test_logout_everywhere_writes_audit_event(db):
    from src.models.prompt_event import PromptEvent

    kc = _mock_kc()
    app = _make_app(db, kc)
    token = make_jwt(sub="logout-audit-user")

    with TestClient(app, raise_server_exceptions=True) as c:
        c.post("/api/v1/me/logout-everywhere", headers={"Authorization": f"Bearer {token}"})

    event = (
        db.query(PromptEvent)
        .filter(PromptEvent.action == "logout_everywhere", PromptEvent.entity_type == "user")
        .first()
    )
    assert event is not None


def test_logout_everywhere_skips_already_revoked_keys(db):
    kc = _mock_kc()
    app = _make_app(db, kc)
    token = make_jwt(sub="logout-skip-revoked-user")

    with TestClient(app, raise_server_exceptions=True) as c:
        r_key = c.post("/api/v1/me/api-keys", json={"label": "k"}, headers={"Authorization": f"Bearer {token}"})
        key_id = r_key.json()["data"]["id"]
        # Revoke it first
        c.delete(f"/api/v1/me/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
        kc.reset_mock()

        r = c.post("/api/v1/me/logout-everywhere", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 204
    # Already-revoked key is not re-revoked
    kc.revoke_session.assert_not_called()


# ---------------------------------------------------------------------------
# Partial-failure paths
# ---------------------------------------------------------------------------

def test_logout_everywhere_502_on_session_logout_failure(db):
    kc = _mock_kc(logout_side_effect=KeycloakError("sessions gone"))
    app = _make_app(db, kc)
    token = make_jwt(sub="logout-session-fail-user")

    with TestClient(app, raise_server_exceptions=True) as c:
        r = c.post("/api/v1/me/logout-everywhere", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 502
    error = r.json()["detail"]["error"]
    assert error["code"] == "KEYCLOAK_ERROR"
    assert "failures" in error
    assert any("session logout" in f for f in error["failures"])


def test_logout_everywhere_502_on_key_revocation_failure(db):
    kc = _mock_kc(revoke_side_effect=KeycloakError("session gone"))
    app = _make_app(db, kc)
    token = make_jwt(sub="logout-key-fail-user")

    with TestClient(app, raise_server_exceptions=True) as c:
        c.post("/api/v1/me/api-keys", json={"label": "k"}, headers={"Authorization": f"Bearer {token}"})
        kc.revoke_session.side_effect = KeycloakError("session gone")

        r = c.post("/api/v1/me/logout-everywhere", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 502
    error = r.json()["detail"]["error"]
    assert error["code"] == "KEYCLOAK_ERROR"
    assert "failures" in error


def test_logout_everywhere_partial_failure_still_revokes_successful_keys(db):
    """Keys that Keycloak successfully revokes are marked revoked in DB even if others fail."""
    from src.models.api_key import ApiKey

    # First revoke_session call succeeds; second fails.
    call_count = 0

    def revoke_side_effect(session_id):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise KeycloakError("second key failed")

    kc = _mock_kc()
    kc.revoke_session.side_effect = revoke_side_effect

    app = _make_app(db, kc)
    token = make_jwt(sub="partial-fail-user")

    with TestClient(app, raise_server_exceptions=True) as c:
        r1 = c.post("/api/v1/me/api-keys", json={"label": "k1"}, headers={"Authorization": f"Bearer {token}"})
        r2 = c.post("/api/v1/me/api-keys", json={"label": "k2"}, headers={"Authorization": f"Bearer {token}"})
        key1_id = r1.json()["data"]["id"]
        key2_id = r2.json()["data"]["id"]

        kc.reset_mock()
        kc.revoke_session.side_effect = revoke_side_effect

        r = c.post("/api/v1/me/logout-everywhere", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 502

    key1 = db.query(ApiKey).filter(ApiKey.id == key1_id).first()
    key2 = db.query(ApiKey).filter(ApiKey.id == key2_id).first()
    # First key was revoked before the failure
    assert key1.revoked_at is not None
    # Second key was not revoked (Keycloak call failed)
    assert key2.revoked_at is None


def test_logout_everywhere_requires_auth(db):
    kc = _mock_kc()
    app = _make_app(db, kc)
    with TestClient(app, raise_server_exceptions=True) as c:
        r = c.post("/api/v1/me/logout-everywhere")
    assert r.status_code == 401
