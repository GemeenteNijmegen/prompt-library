"""DCR-restriction smoke tests: org-deploy client must not obtain restricted scopes.

Proves both sides of the restriction model with real tokens against the live stack:

  Token-issuance: the org-deploy-example client's access token lacks admin:*,
  prompt:publish:public, and prompt:moderate; the first-party gallery-test-client
  token carries all of them.

  Enforcement: POST /api/v1/tags (requires admin:manage_taxonomy) returns 403 for
  the org-deploy client and succeeds (non-403) for the first-party client.

Requires a running Keycloak + gallery-api stack. See tests/smoke/conftest.py.
"""
import base64
import json

import httpx
import pytest

from tests.smoke.conftest import skip_if_no_stack

_RESTRICTED_SCOPES = {
    "admin:manage_taxonomy",
    "admin:manage_users",
    "admin:read_audit",
    "prompt:publish:public",
    "prompt:moderate",
}

_SMOKE_TAG_NAME = "smoke-dcr-restriction-test"


def _token_scopes(token: str) -> set[str]:
    """Decode JWT payload without signature verification and return the permission
    set, carried as realm roles in ``realm_access.roles``."""
    payload_b64 = token.split(".")[1]
    # Restore base64 padding
    payload_b64 += "=" * (-len(payload_b64) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload_b64))
    return set((claims.get("realm_access") or {}).get("roles") or [])


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Token-issuance side
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@skip_if_no_stack
def test_org_deploy_token_lacks_restricted_scopes(org_deploy_token: str):
    """org-deploy-example client credentials token must carry no restricted scopes."""
    scopes = _token_scopes(org_deploy_token)
    present = _RESTRICTED_SCOPES & scopes
    assert not present, (
        f"org-deploy token must not include restricted scopes, but found: {present}"
    )


@pytest.mark.smoke
@skip_if_no_stack
def test_first_party_token_has_restricted_scopes(rs256_token: str):
    """gallery-test-client credentials token must carry all restricted scopes."""
    scopes = _token_scopes(rs256_token)
    missing = _RESTRICTED_SCOPES - scopes
    assert not missing, (
        f"first-party token is missing expected restricted scopes: {missing}"
    )


# ---------------------------------------------------------------------------
# Enforcement side
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@skip_if_no_stack
def test_restricted_endpoint_rejects_org_deploy_client(
    api_url: str, org_deploy_token: str
):
    """POST /api/v1/tags must return 403 for the DCR-restricted org-deploy client."""
    resp = httpx.post(
        f"{api_url}/api/v1/tags",
        json={"name": _SMOKE_TAG_NAME},
        headers=_auth(org_deploy_token),
        timeout=10.0,
    )
    assert resp.status_code == 403, (
        f"Expected 403 for org-deploy client on restricted endpoint, "
        f"got {resp.status_code}: {resp.text}"
    )


@pytest.mark.smoke
@skip_if_no_stack
def test_restricted_endpoint_accepts_first_party_client(
    api_url: str, rs256_token: str
):
    """POST /api/v1/tags must succeed (non-403) for the first-party gallery-test-client."""
    resp = httpx.post(
        f"{api_url}/api/v1/tags",
        json={"name": _SMOKE_TAG_NAME},
        headers=_auth(rs256_token),
        timeout=10.0,
    )
    assert resp.status_code != 403, (
        f"Expected non-403 for first-party client on restricted endpoint, "
        f"got {resp.status_code}: {resp.text}"
    )
    # Clean up the tag if it was created
    if resp.status_code == 201:
        tag_id = resp.json()["data"]["id"]
        httpx.delete(
            f"{api_url}/api/v1/tags/{tag_id}",
            headers=_auth(rs256_token),
            timeout=10.0,
        )
