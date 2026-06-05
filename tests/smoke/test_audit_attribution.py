"""Smoke tests: audit trail client_id/azp attribution with real Keycloak tokens.

Verifies (against a live Keycloak + gallery-api stack) that state-changing
actions produce audit events whose client_id correctly identifies:
  - the Keycloak client (azp) for bearer-token requests
  - a different client when a different OAuth client acts
  - the specific API key (apikey:<id>) for opaque-key requests

This is the end-to-end complement to the unit test
tests/test_api_key_auth.py::test_api_key_request_attributed_to_key_in_audit.
Requires a running Keycloak + gallery-api stack. See tests/smoke/conftest.py.
"""
import pytest
import httpx

from tests.smoke.conftest import (
    _KC_CLIENT_ID,
    _KC_CLIENT_SECRET,
    _KC_ORG_CLIENT_ID,
    _KC_ORG_CLIENT_SECRET,
    _KC_REALM,
    _fetch_token_or_skip,
    skip_if_no_stack,
)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_prompt(api_url: str, token: str, title: str) -> dict:
    resp = httpx.post(
        f"{api_url}/api/v1/prompts",
        json={
            "title": title,
            "description": "Audit attribution smoke test",
            "prompt_text": "Smoke test prompt.",
            "status": "draft",
            "visibility": "public",
        },
        headers=_auth(token),
        timeout=10.0,
    )
    assert resp.status_code == 201, (
        f"Failed to create prompt: {resp.status_code} {resp.text}"
    )
    return resp.json()["data"]


def _delete_prompt(api_url: str, token: str, prompt_id: int) -> None:
    httpx.delete(
        f"{api_url}/api/v1/prompts/{prompt_id}",
        headers=_auth(token),
        timeout=10.0,
    )


def _get_audit_events(api_url: str, admin_token: str, entity_type: str, entity_id: int) -> list:
    resp = httpx.get(
        f"{api_url}/api/v1/admin/audit",
        params={"entity_type": entity_type, "entity_id": str(entity_id)},
        headers=_auth(admin_token),
        timeout=10.0,
    )
    assert resp.status_code == 200, (
        f"GET /admin/audit failed: {resp.status_code} {resp.text}"
    )
    return resp.json()["data"]


@pytest.mark.smoke
@skip_if_no_stack
def test_keycloak_client_attributed_in_audit(api_url: str, rs256_token: str):
    """A prompt created via gallery-test-client has client_id=gallery-test-client in audit."""
    prompt = _create_prompt(api_url, rs256_token, "Smoke: audit-attribution gallery-test-client")
    prompt_id = prompt["id"]
    try:
        events = _get_audit_events(api_url, rs256_token, "prompt", prompt_id)
        created_events = [e for e in events if e["action"] == "created"]
        assert created_events, f"No 'created' audit event found for prompt {prompt_id}"
        assert created_events[0]["client_id"] == _KC_CLIENT_ID, (
            f"Expected client_id={_KC_CLIENT_ID!r}, got {created_events[0]['client_id']!r}"
        )
    finally:
        _delete_prompt(api_url, rs256_token, prompt_id)


@pytest.mark.smoke
@skip_if_no_stack
def test_org_deploy_client_attributed_differently(api_url: str, rs256_token: str, org_deploy_token: str):
    """A prompt created via org-deploy-example has client_id=org-deploy-example in audit."""
    prompt = _create_prompt(api_url, org_deploy_token, "Smoke: audit-attribution org-deploy")
    prompt_id = prompt["id"]
    try:
        events = _get_audit_events(api_url, rs256_token, "prompt", prompt_id)
        created_events = [e for e in events if e["action"] == "created"]
        assert created_events, f"No 'created' audit event found for prompt {prompt_id}"
        assert created_events[0]["client_id"] == _KC_ORG_CLIENT_ID, (
            f"Expected client_id={_KC_ORG_CLIENT_ID!r}, got {created_events[0]['client_id']!r}"
        )
        assert created_events[0]["client_id"] != _KC_CLIENT_ID, (
            "org-deploy event must be attributed to a different client than gallery-test-client"
        )
    finally:
        _delete_prompt(api_url, org_deploy_token, prompt_id)


@pytest.mark.smoke
@skip_if_no_stack
def test_api_key_attributed_as_apikey_in_audit(api_url: str, rs256_user_token: str, rs256_token: str):
    """A prompt created via an opaque API key has client_id=apikey:<id> in audit."""
    # Issue an API key using the interactive user token.
    key_resp = httpx.post(
        f"{api_url}/api/v1/me/api-keys",
        json={"label": "smoke-audit-key"},
        headers=_auth(rs256_user_token),
        timeout=10.0,
    )
    assert key_resp.status_code == 201, (
        f"Expected 201 from POST /me/api-keys, got {key_resp.status_code}: {key_resp.text}"
    )
    key_data = key_resp.json()["data"]
    api_key = key_data["token"]
    key_id = key_data["id"]
    assert api_key.startswith("pg_"), "Issued key must be an opaque pg_… token"

    prompt = _create_prompt(api_url, api_key, "Smoke: audit-attribution api-key")
    prompt_id = prompt["id"]
    try:
        events = _get_audit_events(api_url, rs256_token, "prompt", prompt_id)
        created_events = [e for e in events if e["action"] == "created"]
        assert created_events, f"No 'created' audit event found for prompt {prompt_id}"
        expected_client_id = f"apikey:{key_id}"
        assert created_events[0]["client_id"] == expected_client_id, (
            f"Expected client_id={expected_client_id!r}, got {created_events[0]['client_id']!r}"
        )
    finally:
        _delete_prompt(api_url, api_key, prompt_id)
        # Revoke the key so it doesn't accumulate across smoke runs.
        httpx.delete(
            f"{api_url}/api/v1/me/api-keys/{key_id}",
            headers=_auth(rs256_user_token),
            timeout=10.0,
        )
