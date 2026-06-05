"""Tests for POST /api/v1/me/logout-everywhere.

Under the opaque-key model, API-key revocation is a DB update — only the
interactive-session logout touches Keycloak, so that is the only mockable
failure surface.
"""
from unittest.mock import MagicMock

from starlette.testclient import TestClient

from src.services.keycloak_client import KeycloakError, get_keycloak_client
from tests.conftest import make_jwt


def _mock_kc(logout_side_effect=None):
    kc = MagicMock()
    if logout_side_effect:
        kc.logout_all_sessions.side_effect = logout_side_effect
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


def test_logout_everywhere_revokes_all_active_api_keys_in_db(db):
    from src.models.api_key import ApiKey

    kc = _mock_kc()
    app = _make_app(db, kc)
    token = make_jwt(sub="logout-with-keys-user")

    with TestClient(app, raise_server_exceptions=True) as c:
        r1 = c.post("/api/v1/me/api-keys", json={"label": "key1"}, headers={"Authorization": f"Bearer {token}"})
        r2 = c.post("/api/v1/me/api-keys", json={"label": "key2"}, headers={"Authorization": f"Bearer {token}"})
        id1 = r1.json()["data"]["id"]
        id2 = r2.json()["data"]["id"]

        r = c.post("/api/v1/me/logout-everywhere", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 204
    assert db.query(ApiKey).filter(ApiKey.id == id1).first().revoked_at is not None
    assert db.query(ApiKey).filter(ApiKey.id == id2).first().revoked_at is not None


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


def test_logout_everywhere_leaves_already_revoked_keys_untouched(db):
    from src.models.api_key import ApiKey

    kc = _mock_kc()
    app = _make_app(db, kc)
    token = make_jwt(sub="logout-skip-revoked-user")

    with TestClient(app, raise_server_exceptions=True) as c:
        r_key = c.post("/api/v1/me/api-keys", json={"label": "k"}, headers={"Authorization": f"Bearer {token}"})
        key_id = r_key.json()["data"]["id"]
        c.delete(f"/api/v1/me/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
        first_revoked_at = db.query(ApiKey).filter(ApiKey.id == key_id).first().revoked_at

        r = c.post("/api/v1/me/logout-everywhere", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 204
    # The original revocation timestamp is not overwritten.
    db.expire_all()
    assert db.query(ApiKey).filter(ApiKey.id == key_id).first().revoked_at == first_revoked_at


# ---------------------------------------------------------------------------
# Failure path — only the interactive-session logout can fail at Keycloak
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
    assert any("session logout" in f for f in error["failures"])


def test_logout_everywhere_revokes_keys_even_if_session_logout_fails(db):
    """Keys are revoked in the DB even when the Keycloak session logout fails."""
    from src.models.api_key import ApiKey

    kc = _mock_kc(logout_side_effect=KeycloakError("sessions gone"))
    app = _make_app(db, kc)
    token = make_jwt(sub="logout-keys-despite-fail-user")

    with TestClient(app, raise_server_exceptions=True) as c:
        r_key = c.post("/api/v1/me/api-keys", json={"label": "k"}, headers={"Authorization": f"Bearer {token}"})
        key_id = r_key.json()["data"]["id"]

        r = c.post("/api/v1/me/logout-everywhere", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 502
    assert db.query(ApiKey).filter(ApiKey.id == key_id).first().revoked_at is not None


def test_logout_everywhere_requires_auth(db):
    kc = _mock_kc()
    app = _make_app(db, kc)
    with TestClient(app, raise_server_exceptions=True) as c:
        r = c.post("/api/v1/me/logout-everywhere")
    assert r.status_code == 401
