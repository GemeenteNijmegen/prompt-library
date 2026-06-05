"""Smoke tests: opaque API-key issuance, use, and logout-everywhere lifecycle.

Exercises (against a live Keycloak + gallery-api stack):
  - POST /me/api-keys → opaque pg_… key → authenticated request to the gallery
  - DELETE /me/api-keys/{id} → key rejected by the gallery (401)
  - POST /me/logout-everywhere → all keys rejected by the gallery (401)

Unlike the previous offline-token design, the key is validated by the gallery
itself (DB hash lookup), so these assertions hit the gallery API directly and
never round-trip through Keycloak. See tests/smoke/conftest.py.
"""
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


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.smoke
@skip_if_no_stack
def test_api_key_issuance_and_revoke(api_url: str, rs256_user_token: str):
    """Full API-key lifecycle: issue → authenticate with the key → revoke → rejected."""
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
    api_key = data["token"]
    assert api_key.startswith("pg_"), "POST /me/api-keys must return an opaque pg_… key"

    # 2. The opaque key must authenticate a request to the gallery API directly.
    me_resp = httpx.get(f"{api_url}/api/v1/me", headers=_auth(api_key), timeout=10.0)
    assert me_resp.status_code == 200, (
        f"API key must be accepted by the gallery, got {me_resp.status_code}: {me_resp.text}"
    )

    # 3. Revoke the API key.
    del_resp = httpx.delete(
        f"{api_url}/api/v1/me/api-keys/{key_id}",
        headers=_auth(rs256_user_token),
        timeout=10.0,
    )
    assert del_resp.status_code == 204, (
        f"Expected 204 on revoke, got {del_resp.status_code}: {del_resp.text}"
    )

    # 4. After revocation the key must be rejected by the gallery.
    post_revoke_resp = httpx.get(f"{api_url}/api/v1/me", headers=_auth(api_key), timeout=10.0)
    assert post_revoke_resp.status_code == 401, (
        f"Revoked key must be rejected, got {post_revoke_resp.status_code}: {post_revoke_resp.text}"
    )

    # 5. Revoked key must not appear in the active-key list.
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
    """logout-everywhere revokes all keys (rejected by the gallery) and clears the list."""
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
    api_key = resp.json()["data"]["token"]

    # 2. Sanity-check: the key works before logout.
    pre_resp = httpx.get(f"{api_url}/api/v1/me", headers=_auth(api_key), timeout=10.0)
    assert pre_resp.status_code == 200, (
        f"Key must be valid before logout, got {pre_resp.status_code}: {pre_resp.text}"
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

    # 4. API-key list must be empty — the key is revoked in the DB.
    list_resp = httpx.get(
        f"{api_url}/api/v1/me/api-keys",
        headers=_auth(user_token),
        timeout=10.0,
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["data"] == [], "All keys must be revoked after logout-everywhere"

    # 5. The key must now be rejected by the gallery.
    post_logout_resp = httpx.get(f"{api_url}/api/v1/me", headers=_auth(api_key), timeout=10.0)
    assert post_logout_resp.status_code == 401, (
        f"Key must be rejected after logout-everywhere, "
        f"got {post_logout_resp.status_code}: {post_logout_resp.text}"
    )
