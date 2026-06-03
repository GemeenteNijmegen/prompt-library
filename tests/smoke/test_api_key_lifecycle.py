"""Smoke tests: API-key issuance, use, and logout-everywhere lifecycle.

Exercises:
  - POST /me/api-keys → token exchange against Keycloak → authenticated request
  - DELETE /me/api-keys/{id} → offline token rejected by Keycloak
  - POST /me/logout-everywhere → all offline tokens invalidated

Requires a running Keycloak + gallery-api stack. See tests/smoke/conftest.py.
"""
import os

import httpx
import pytest

from tests.smoke.conftest import (
    _KC_ALICE_PASSWORD,
    _KC_ALICE_USERNAME,
    _KC_CLIENT_ID,
    _KC_CLIENT_SECRET,
    _KC_REALM,
    _fetch_token_or_skip,
    skip_if_no_stack,
)

_KC_APIKEY_CLIENT_ID = os.environ.get("KEYCLOAK_API_KEY_CLIENT_ID", "gallery-apikey-issuer")
_KC_APIKEY_CLIENT_SECRET = os.environ.get("KEYCLOAK_API_KEY_CLIENT_SECRET", "apikey-issuer-secret")


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _exchange_offline_token(kc_url: str, offline_token: str) -> httpx.Response:
    """Try to exchange an offline token for a fresh access token via Keycloak."""
    token_url = f"{kc_url}/realms/{_KC_REALM}/protocol/openid-connect/token"
    return httpx.post(
        token_url,
        data={
            "grant_type": "refresh_token",
            "refresh_token": offline_token,
            "client_id": _KC_APIKEY_CLIENT_ID,
            "client_secret": _KC_APIKEY_CLIENT_SECRET,
        },
        timeout=10.0,
    )


@pytest.mark.smoke
@skip_if_no_stack
def test_api_key_issuance_and_revoke(kc_url: str, api_url: str, rs256_user_token: str):
    """Full API-key lifecycle: issue → exchange offline token → authenticate → revoke."""
    # 1. Issue an API key using the user's interactive access token.
    resp = httpx.post(
        f"{api_url}/api/v1/me/api-keys",
        json={"label": "smoke-lifecycle-key"},
        headers=_auth(rs256_user_token),
        timeout=10.0,
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    data = resp.json()["data"]
    key_id = data["id"]
    offline_token = data["token"]
    assert offline_token, "POST /me/api-keys must return a non-empty offline token"

    # 2. Exchange the offline token for a fresh access token at Keycloak.
    exchange_resp = _exchange_offline_token(kc_url, offline_token)
    assert exchange_resp.status_code == 200, (
        f"Offline token must be exchangeable for an access token, "
        f"got {exchange_resp.status_code}: {exchange_resp.text}"
    )
    fresh_access_token = exchange_resp.json()["access_token"]

    # 3. The fresh access token must authenticate a request to the gallery API.
    me_resp = httpx.get(
        f"{api_url}/api/v1/me",
        headers=_auth(fresh_access_token),
        timeout=10.0,
    )
    assert me_resp.status_code == 200, (
        f"Access token derived from offline token must be accepted, "
        f"got {me_resp.status_code}: {me_resp.text}"
    )

    # 4. Revoke the API key.
    del_resp = httpx.delete(
        f"{api_url}/api/v1/me/api-keys/{key_id}",
        headers=_auth(rs256_user_token),
        timeout=10.0,
    )
    assert del_resp.status_code == 204, (
        f"Expected 204 on revoke, got {del_resp.status_code}: {del_resp.text}"
    )

    # 5. After revocation the offline token must be rejected by Keycloak.
    post_revoke_resp = _exchange_offline_token(kc_url, offline_token)
    assert post_revoke_resp.status_code in (400, 401), (
        f"Revoked offline token must be rejected by Keycloak, "
        f"got {post_revoke_resp.status_code}: {post_revoke_resp.text}"
    )

    # 6. Revoked key must not appear in the active-key list.
    list_resp = httpx.get(
        f"{api_url}/api/v1/me/api-keys",
        headers=_auth(rs256_user_token),
        timeout=10.0,
    )
    assert list_resp.status_code == 200
    ids = [k["id"] for k in list_resp.json()["data"]]
    assert key_id not in ids, "Revoked key must not appear in GET /me/api-keys"


@pytest.mark.smoke
@skip_if_no_stack
def test_logout_everywhere_invalidates_api_key(kc_url: str, api_url: str):
    """logout-everywhere revokes all offline tokens and marks API keys revoked in the DB."""
    # Fetch a fresh token inline so we don't pollute the session-scoped alice_token fixture.
    user_token = _fetch_token_or_skip(
        keycloak_url=kc_url,
        realm=_KC_REALM,
        client_id=_KC_CLIENT_ID,
        client_secret=_KC_CLIENT_SECRET,
        grant_type="password",
        username=_KC_ALICE_USERNAME,
        password=_KC_ALICE_PASSWORD,
    )

    # 1. Issue an API key.
    resp = httpx.post(
        f"{api_url}/api/v1/me/api-keys",
        json={"label": "smoke-logout-key"},
        headers=_auth(user_token),
        timeout=10.0,
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    data = resp.json()["data"]
    key_id = data["id"]
    offline_token = data["token"]

    # 2. Sanity-check: offline token is exchangeable before logout.
    pre_resp = _exchange_offline_token(kc_url, offline_token)
    assert pre_resp.status_code == 200, (
        f"Offline token must be valid before logout, got {pre_resp.status_code}: {pre_resp.text}"
    )

    # 3. Trigger logout-everywhere.
    logout_resp = httpx.post(
        f"{api_url}/api/v1/me/logout-everywhere",
        headers=_auth(user_token),
        timeout=10.0,
    )
    assert logout_resp.status_code == 204, (
        f"Expected 204 from logout-everywhere, got {logout_resp.status_code}: {logout_resp.text}"
    )

    # 4. API-key list must be empty — the key is marked revoked in the DB.
    list_resp = httpx.get(
        f"{api_url}/api/v1/me/api-keys",
        headers=_auth(user_token),
        timeout=10.0,
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["data"] == [], (
        "All API keys must be revoked after logout-everywhere"
    )

    # 5. The offline token must be rejected by Keycloak (session revoked).
    post_logout_resp = _exchange_offline_token(kc_url, offline_token)
    assert post_logout_resp.status_code in (400, 401), (
        f"Offline token must be rejected by Keycloak after logout-everywhere, "
        f"got {post_logout_resp.status_code}: {post_logout_resp.text}"
    )
