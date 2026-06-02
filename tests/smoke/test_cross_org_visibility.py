"""Cross-org visibility isolation smoke tests with real RS256 tokens.

Uses seeded users alice (org-a) and bob (org-b) to verify that the org_id
claim emitted by Keycloak is correctly enforced by the row-level visibility
filter end-to-end:

  - org-scoped (published_org) prompts created by an org-a user are NOT
    visible to an org-b user
  - public (published_public) prompts are visible across orgs

Requires a running Keycloak + gallery-api stack. See tests/smoke/conftest.py.
"""
import pytest
import httpx

from tests.smoke.conftest import skip_if_no_stack


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_prompt(api_url: str, token: str, status: str, title: str) -> dict:
    resp = httpx.post(
        f"{api_url}/api/v1/prompts",
        json={
            "title": title,
            "description": "Smoke test prompt",
            "prompt_text": "This is a smoke test prompt.",
            "status": status,
            "visibility": "public",
        },
        headers=_auth(token),
        timeout=10.0,
    )
    assert resp.status_code == 201, (
        f"Failed to create {status!r} prompt: {resp.status_code} {resp.text}"
    )
    return resp.json()["data"]


def _delete_prompt(api_url: str, token: str, prompt_id: int) -> None:
    httpx.delete(
        f"{api_url}/api/v1/prompts/{prompt_id}",
        headers=_auth(token),
        timeout=10.0,
    )


@pytest.mark.smoke
@skip_if_no_stack
def test_org_scoped_prompt_hidden_from_other_org(api_url: str, alice_token: str, bob_token: str):
    """published_org prompt created by alice (org-a) must be invisible to bob (org-b)."""
    prompt = _create_prompt(
        api_url, alice_token, "published_org", "Smoke: org-a private prompt"
    )
    prompt_id = prompt["id"]
    try:
        # alice (same org) can see it
        resp_alice = httpx.get(
            f"{api_url}/api/v1/prompts/{prompt_id}",
            headers=_auth(alice_token),
            timeout=10.0,
        )
        assert resp_alice.status_code == 200, (
            f"alice should see her own org-scoped prompt, got {resp_alice.status_code}: {resp_alice.text}"
        )

        # bob (different org) cannot see it
        resp_bob = httpx.get(
            f"{api_url}/api/v1/prompts/{prompt_id}",
            headers=_auth(bob_token),
            timeout=10.0,
        )
        assert resp_bob.status_code == 404, (
            f"bob (org-b) should NOT see org-a's published_org prompt, "
            f"got {resp_bob.status_code}: {resp_bob.text}"
        )
    finally:
        _delete_prompt(api_url, alice_token, prompt_id)


@pytest.mark.smoke
@skip_if_no_stack
def test_public_prompt_visible_across_orgs(api_url: str, alice_token: str, bob_token: str):
    """published_public prompt created by alice must be visible to bob (different org)."""
    prompt = _create_prompt(
        api_url, alice_token, "published_public", "Smoke: public cross-org prompt"
    )
    prompt_id = prompt["id"]
    try:
        resp_alice = httpx.get(
            f"{api_url}/api/v1/prompts/{prompt_id}",
            headers=_auth(alice_token),
            timeout=10.0,
        )
        assert resp_alice.status_code == 200, (
            f"alice should see her own public prompt, got {resp_alice.status_code}"
        )

        resp_bob = httpx.get(
            f"{api_url}/api/v1/prompts/{prompt_id}",
            headers=_auth(bob_token),
            timeout=10.0,
        )
        assert resp_bob.status_code == 200, (
            f"bob (org-b) should see alice's published_public prompt, "
            f"got {resp_bob.status_code}: {resp_bob.text}"
        )
    finally:
        _delete_prompt(api_url, alice_token, prompt_id)


@pytest.mark.smoke
@skip_if_no_stack
def test_org_scoped_prompt_excluded_from_list_for_other_org(
    api_url: str, alice_token: str, bob_token: str
):
    """published_org prompt must not appear in bob's list response."""
    prompt = _create_prompt(
        api_url, alice_token, "published_org", "Smoke: org-a prompt for list test"
    )
    prompt_id = prompt["id"]
    try:
        resp = httpx.get(
            f"{api_url}/api/v1/prompts",
            headers=_auth(bob_token),
            timeout=10.0,
        )
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["data"]]
        assert prompt_id not in ids, (
            f"org-a prompt {prompt_id} must not appear in bob's (org-b) list"
        )
    finally:
        _delete_prompt(api_url, alice_token, prompt_id)
