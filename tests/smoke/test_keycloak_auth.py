"""Tracer-bullet smoke tests: real RS256 token accepted; stale HS256 rejected.

Also covers role-scope fidelity (each persona gets exactly the right scopes,
not a superset) and org_id claim accuracy — the two classes of bug fixed in
the realm-export.json role-mapper refactor.

Requires a running Keycloak + gallery-api stack. See tests/smoke/conftest.py.
"""
import time

import pytest
from jose import jwt as jose_jwt

from tests.smoke.conftest import (
    _KC_CLIENT_ID,
    _KC_CLIENT_SECRET,
    _KC_REALM,
    _fetch_token_or_skip,
    skip_if_no_stack,
)

# Expected scopes per persona (based on composite role → granular role mapping).
# Update these sets whenever the PLAN.md permission catalogue changes.
_VIEWER_SCOPES = {"prompt:read", "apikey:create"}
_CONTRIBUTOR_SCOPES = _VIEWER_SCOPES | {
    "prompt:read:restricted", "prompt:create", "prompt:write",
    "prompt:rate", "prompt:image",
}
_PUBLISHER_SCOPES = _CONTRIBUTOR_SCOPES | {"prompt:publish"}
_ADMIN_SCOPES = _PUBLISHER_SCOPES | {
    "prompt:publish:public", "prompt:moderate",
    "admin:manage_taxonomy", "admin:manage_users", "admin:read_audit",
}
_ALL_PERMISSION_SCOPES = _ADMIN_SCOPES


def _permission_scopes(token: str) -> set[str]:
    """Return the permission scopes (carried as realm roles in ``realm_access.roles``)
    from an RS256 token without verifying the signature."""
    claims = jose_jwt.get_unverified_claims(token)
    roles = (claims.get("realm_access") or {}).get("roles") or []
    return set(roles) & _ALL_PERMISSION_SCOPES


@pytest.mark.smoke
@skip_if_no_stack
def test_rs256_token_accepted(api_url: str, rs256_token: str):
    """A real RS256 token issued by local Keycloak must reach a protected endpoint."""
    import httpx

    resp = httpx.get(
        f"{api_url}/api/v1/me",
        headers={"Authorization": f"Bearer {rs256_token}"},
        timeout=10.0,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "data" in data or "id" in data or "sub" in data or "email" in data


@pytest.mark.smoke
@skip_if_no_stack
def test_hs256_token_rejected_when_jwks_uri_set(api_url: str):
    """When the gallery API is configured with JWKS_URI, HS256 tokens must be rejected."""
    stale_token = jose_jwt.encode(
        {
            "sub": "attacker-001",
            "iss": "http://localhost:9000",
            "aud": "prompt-gallery-api",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
            "scope": ["prompt:read"],
        },
        "any-secret-key",
        algorithm="HS256",
    )

    import httpx

    resp = httpx.get(
        f"{api_url}/api/v1/me",
        headers={"Authorization": f"Bearer {stale_token}"},
        timeout=10.0,
    )
    assert resp.status_code == 401, (
        f"HS256 token should be rejected (401) when JWKS_URI is active, "
        f"but got {resp.status_code}: {resp.text}"
    )


@pytest.mark.smoke
@skip_if_no_stack
def test_rs256_user_token_accepted(api_url: str, rs256_user_token: str):
    """A password-grant RS256 token for the dev user must also be accepted."""
    import httpx

    resp = httpx.get(
        f"{api_url}/api/v1/me",
        headers={"Authorization": f"Bearer {rs256_user_token}"},
        timeout=10.0,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


# ── Role-scope fidelity ───────────────────────────────────────────────────────
# These tests catch the class of bug where every user receives every permission
# scope regardless of their persona role (scope inflation).


@pytest.mark.smoke
@skip_if_no_stack
def test_alice_publisher_has_exactly_publisher_scopes(kc_url: str, alice_token: str):
    """alice (org-a publisher) must have publisher-level scopes and no admin extras."""
    got = _permission_scopes(alice_token)
    assert got == _PUBLISHER_SCOPES, (
        f"alice scope mismatch.\n"
        f"  expected: {sorted(_PUBLISHER_SCOPES)}\n"
        f"  got:      {sorted(got)}\n"
        f"  extra:    {sorted(got - _PUBLISHER_SCOPES)}\n"
        f"  missing:  {sorted(_PUBLISHER_SCOPES - got)}"
    )


@pytest.mark.smoke
@skip_if_no_stack
def test_bob_viewer_has_exactly_viewer_scopes(kc_url: str):
    """bob (viewer) must have only viewer-level scopes."""
    bob_token = _fetch_token_or_skip(
        keycloak_url=kc_url,
        realm=_KC_REALM,
        client_id=_KC_CLIENT_ID,
        client_secret=_KC_CLIENT_SECRET,
        grant_type="password",
        username="bob",
        password="dev",
    )
    got = _permission_scopes(bob_token)
    assert got == _VIEWER_SCOPES, (
        f"bob scope mismatch.\n"
        f"  expected: {sorted(_VIEWER_SCOPES)}\n"
        f"  got:      {sorted(got)}\n"
        f"  extra:    {sorted(got - _VIEWER_SCOPES)}"
    )


@pytest.mark.smoke
@skip_if_no_stack
def test_admin_user_has_all_scopes(kc_url: str, rs256_user_token: str):
    """devuser (admin) must hold all 13 permission scopes."""
    got = _permission_scopes(rs256_user_token)
    assert got == _ADMIN_SCOPES, (
        f"devuser scope mismatch.\n"
        f"  expected: {sorted(_ADMIN_SCOPES)}\n"
        f"  got:      {sorted(got)}\n"
        f"  missing:  {sorted(_ADMIN_SCOPES - got)}"
    )


# ── org_id claim accuracy ─────────────────────────────────────────────────────
# Catches the class of bug where Keycloak org membership or user attributes
# are not wired up, causing the wrong (or absent) org_id claim.


@pytest.mark.smoke
@skip_if_no_stack
def test_alice_token_carries_org_a(alice_token: str):
    """alice's token must carry org_id=org-a."""
    claims = jose_jwt.get_unverified_claims(alice_token)
    assert claims.get("org_id") == "org-a", (
        f"Expected org_id='org-a', got {claims.get('org_id')!r}"
    )


@pytest.mark.smoke
@skip_if_no_stack
def test_bob_token_carries_org_b(kc_url: str):
    """bob's token must carry org_id=org-b."""
    bob_token = _fetch_token_or_skip(
        keycloak_url=kc_url,
        realm=_KC_REALM,
        client_id=_KC_CLIENT_ID,
        client_secret=_KC_CLIENT_SECRET,
        grant_type="password",
        username="bob",
        password="dev",
    )
    claims = jose_jwt.get_unverified_claims(bob_token)
    assert claims.get("org_id") == "org-b", (
        f"Expected org_id='org-b', got {claims.get('org_id')!r}"
    )
