"""Tests for POST/GET/DELETE /api/v1/me/api-keys.

Keycloak calls are mocked via dependency override on get_keycloak_client.
"""
import pytest
from unittest.mock import MagicMock

from tests.conftest import make_jwt
from src.services.keycloak_client import get_keycloak_client, KeycloakError


_FAKE_SESSION_ID = "kc-session-abc123"
_FAKE_OFFLINE_TOKEN = "eyJ_fake_offline_token"


def _mock_kc(issue_side_effect=None, revoke_side_effect=None):
    kc = MagicMock()
    if issue_side_effect:
        kc.issue_offline_token.side_effect = issue_side_effect
    else:
        kc.issue_offline_token.return_value = (_FAKE_OFFLINE_TOKEN, _FAKE_SESSION_ID)
    if revoke_side_effect:
        kc.revoke_session.side_effect = revoke_side_effect
    return kc


@pytest.fixture()
def client_with_kc(db):
    """TestClient with Keycloak mocked to succeed."""
    from src.main import create_app
    from src.dependencies import get_db

    app = create_app()

    mock_kc = _mock_kc()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_keycloak_client] = lambda: mock_kc

    from starlette.testclient import TestClient
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c, mock_kc


# ---------------------------------------------------------------------------
# POST /api/v1/me/api-keys
# ---------------------------------------------------------------------------

def test_create_api_key_returns_token_once(client_with_kc):
    c, _ = client_with_kc
    token = make_jwt()
    r = c.post(
        "/api/v1/me/api-keys",
        json={"label": "CI pipeline"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["token"] == _FAKE_OFFLINE_TOKEN
    assert data["label"] == "CI pipeline"
    assert "id" in data
    assert "created_at" in data


def test_create_api_key_token_not_in_list(client_with_kc):
    """GET after POST must not expose the raw token."""
    c, _ = client_with_kc
    token = make_jwt()
    c.post(
        "/api/v1/me/api-keys",
        json={"label": "my key"},
        headers={"Authorization": f"Bearer {token}"},
    )
    r = c.get("/api/v1/me/api-keys", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    for item in r.json()["data"]:
        assert "token" not in item


def test_create_api_key_calls_keycloak(client_with_kc):
    c, mock_kc = client_with_kc
    token = make_jwt()
    c.post(
        "/api/v1/me/api-keys",
        json={"label": "test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    mock_kc.issue_offline_token.assert_called_once()
    # The raw bearer token must be forwarded to Keycloak
    call_args = mock_kc.issue_offline_token.call_args[0]
    assert call_args[0] == token


def test_create_api_key_writes_audit_event(client_with_kc, db):
    from src.models.prompt_event import PromptEvent

    c, _ = client_with_kc
    token = make_jwt()
    r = c.post(
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


def test_create_api_key_blocked_without_scope(db):
    from src.main import create_app
    from src.dependencies import get_db
    from starlette.testclient import TestClient

    app = create_app()

    mock_kc = _mock_kc()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_keycloak_client] = lambda: mock_kc

    with TestClient(app, raise_server_exceptions=True) as c:
        token = make_jwt(scope=["prompt:read"])
        r = c.post(
            "/api/v1/me/api-keys",
            json={"label": "should be blocked"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "FORBIDDEN"


def test_create_api_key_keycloak_error_returns_502(db):
    from src.main import create_app
    from src.dependencies import get_db
    from starlette.testclient import TestClient

    app = create_app()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_keycloak_client] = lambda: _mock_kc(
        issue_side_effect=KeycloakError("Keycloak unreachable")
    )

    with TestClient(app, raise_server_exceptions=True) as c:
        token = make_jwt()
        r = c.post(
            "/api/v1/me/api-keys",
            json={"label": "fail"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 502


# ---------------------------------------------------------------------------
# GET /api/v1/me/api-keys
# ---------------------------------------------------------------------------

def test_list_api_keys_empty(client_with_kc):
    c, _ = client_with_kc
    token = make_jwt(sub="list-test-user")
    r = c.get("/api/v1/me/api-keys", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_list_api_keys_returns_own_keys_only(client_with_kc):
    c, _ = client_with_kc
    token_a = make_jwt(sub="user-a")
    token_b = make_jwt(sub="user-b")

    c.post("/api/v1/me/api-keys", json={"label": "key-a"}, headers={"Authorization": f"Bearer {token_a}"})
    c.post("/api/v1/me/api-keys", json={"label": "key-b"}, headers={"Authorization": f"Bearer {token_b}"})

    r = c.get("/api/v1/me/api-keys", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200
    labels = [k["label"] for k in r.json()["data"]]
    assert "key-a" in labels
    assert "key-b" not in labels


def test_list_api_keys_excludes_revoked(client_with_kc):
    c, _ = client_with_kc
    token = make_jwt(sub="revoke-list-user")

    r_create = c.post(
        "/api/v1/me/api-keys",
        json={"label": "to revoke"},
        headers={"Authorization": f"Bearer {token}"},
    )
    key_id = r_create.json()["data"]["id"]

    c.delete(f"/api/v1/me/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})

    r = c.get("/api/v1/me/api-keys", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    ids = [k["id"] for k in r.json()["data"]]
    assert key_id not in ids


# ---------------------------------------------------------------------------
# DELETE /api/v1/me/api-keys/{id}
# ---------------------------------------------------------------------------

def test_revoke_api_key_calls_keycloak(client_with_kc):
    c, mock_kc = client_with_kc
    token = make_jwt(sub="revoke-test-user-1")

    r_create = c.post(
        "/api/v1/me/api-keys",
        json={"label": "to revoke"},
        headers={"Authorization": f"Bearer {token}"},
    )
    key_id = r_create.json()["data"]["id"]

    r_del = c.delete(f"/api/v1/me/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
    assert r_del.status_code == 204

    mock_kc.revoke_session.assert_called_once_with(_FAKE_SESSION_ID)


def test_revoke_api_key_writes_audit_event(client_with_kc, db):
    from src.models.prompt_event import PromptEvent

    c, _ = client_with_kc
    token = make_jwt(sub="revoke-audit-user")

    r_create = c.post(
        "/api/v1/me/api-keys",
        json={"label": "audit revoke"},
        headers={"Authorization": f"Bearer {token}"},
    )
    key_id = r_create.json()["data"]["id"]

    c.delete(f"/api/v1/me/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})

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


def test_revoke_api_key_not_found(client_with_kc):
    c, _ = client_with_kc
    token = make_jwt()
    r = c.delete("/api/v1/me/api-keys/99999", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


def test_revoke_api_key_cross_user_blocked(client_with_kc):
    """User B cannot revoke User A's key."""
    c, _ = client_with_kc
    token_a = make_jwt(sub="cross-user-a")
    token_b = make_jwt(sub="cross-user-b")

    r_create = c.post(
        "/api/v1/me/api-keys",
        json={"label": "a key"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    key_id = r_create.json()["data"]["id"]

    r_del = c.delete(f"/api/v1/me/api-keys/{key_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert r_del.status_code == 404


def test_revoke_api_key_double_revoke_returns_409(client_with_kc):
    c, _ = client_with_kc
    token = make_jwt(sub="double-revoke-user")

    r_create = c.post(
        "/api/v1/me/api-keys",
        json={"label": "double revoke"},
        headers={"Authorization": f"Bearer {token}"},
    )
    key_id = r_create.json()["data"]["id"]

    c.delete(f"/api/v1/me/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
    r2 = c.delete(f"/api/v1/me/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 409


def test_revoke_api_key_keycloak_error_returns_502(db):
    from src.main import create_app
    from src.dependencies import get_db
    from starlette.testclient import TestClient

    app = create_app()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db

    # First create with a working mock, then revoke with a broken one.
    working_kc = _mock_kc()
    app.dependency_overrides[get_keycloak_client] = lambda: working_kc

    with TestClient(app, raise_server_exceptions=True) as c:
        token = make_jwt(sub="kc-error-user")
        r_create = c.post(
            "/api/v1/me/api-keys",
            json={"label": "kc error"},
            headers={"Authorization": f"Bearer {token}"},
        )
        key_id = r_create.json()["data"]["id"]

        broken_kc = _mock_kc(revoke_side_effect=KeycloakError("Keycloak unreachable"))
        app.dependency_overrides[get_keycloak_client] = lambda: broken_kc

        r_del = c.delete(
            f"/api/v1/me/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r_del.status_code == 502
