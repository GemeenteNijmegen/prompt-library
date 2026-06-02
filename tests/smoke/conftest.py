"""Smoke test fixtures for a live Keycloak + gallery-api stack.

These tests are skipped unless the environment is wired up:
  - KEYCLOAK_URL must be set (e.g. http://localhost:8080)
  - GALLERY_API_URL must be set (e.g. http://localhost:8000)

Run with:
    KEYCLOAK_URL=http://localhost:8080 GALLERY_API_URL=http://localhost:8000 \
        pytest tests/smoke -m smoke -v
"""
import os

import pytest


KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "")
GALLERY_API_URL = os.environ.get("GALLERY_API_URL", "")

_KC_REALM = os.environ.get("KEYCLOAK_REALM", "gallery")
_KC_CLIENT_ID = os.environ.get("KEYCLOAK_TEST_CLIENT_ID", "gallery-test-client")
_KC_CLIENT_SECRET = os.environ.get("KEYCLOAK_TEST_CLIENT_SECRET", "test-client-secret")
_KC_USERNAME = os.environ.get("KEYCLOAK_DEV_USERNAME", "devuser")
_KC_PASSWORD = os.environ.get("KEYCLOAK_DEV_PASSWORD", "devpass")

# Seeded cross-org users (passwords fixed in realm-export.json)
_KC_ALICE_USERNAME = os.environ.get("KEYCLOAK_ALICE_USERNAME", "alice")
_KC_ALICE_PASSWORD = os.environ.get("KEYCLOAK_ALICE_PASSWORD", "dev")
_KC_BOB_USERNAME = os.environ.get("KEYCLOAK_BOB_USERNAME", "bob")
_KC_BOB_PASSWORD = os.environ.get("KEYCLOAK_BOB_PASSWORD", "dev")

_stack_live = bool(KEYCLOAK_URL and GALLERY_API_URL)

skip_if_no_stack = pytest.mark.skipif(
    not _stack_live,
    reason="Set KEYCLOAK_URL and GALLERY_API_URL to run smoke tests",
)


def _fetch_token_or_skip(**kwargs) -> str:
    """Call fetch_token and convert network errors to pytest.skip.

    Keycloak accepts TCP connections while still starting up (realm import in
    progress) but resets them before sending a response.  Treating that as a
    skip rather than a hard error gives a cleaner signal than an ERROR row.
    """
    import httpx
    from scripts.keycloak_token import fetch_token
    try:
        return fetch_token(**kwargs)
    except (httpx.TransportError, httpx.ConnectError, OSError) as exc:
        pytest.skip(f"Keycloak unreachable ({type(exc).__name__}: {exc})")


@pytest.fixture(scope="session")
def kc_url() -> str:
    return KEYCLOAK_URL.rstrip("/")


@pytest.fixture(scope="session")
def api_url() -> str:
    return GALLERY_API_URL.rstrip("/")


@pytest.fixture(scope="session")
def rs256_token(kc_url: str) -> str:
    """Fetch a real RS256 access token from Keycloak via client-credentials grant."""
    return _fetch_token_or_skip(
        keycloak_url=kc_url,
        realm=_KC_REALM,
        client_id=_KC_CLIENT_ID,
        client_secret=_KC_CLIENT_SECRET,
        grant_type="client_credentials",
    )


@pytest.fixture(scope="session")
def rs256_user_token(kc_url: str) -> str:
    """Fetch a real RS256 access token via resource-owner password grant."""
    return _fetch_token_or_skip(
        keycloak_url=kc_url,
        realm=_KC_REALM,
        client_id=_KC_CLIENT_ID,
        client_secret=_KC_CLIENT_SECRET,
        grant_type="password",
        username=_KC_USERNAME,
        password=_KC_PASSWORD,
    )


@pytest.fixture(scope="session")
def alice_token(kc_url: str) -> str:
    """RS256 token for alice — seeded org-a contributor."""
    return _fetch_token_or_skip(
        keycloak_url=kc_url,
        realm=_KC_REALM,
        client_id=_KC_CLIENT_ID,
        client_secret=_KC_CLIENT_SECRET,
        grant_type="password",
        username=_KC_ALICE_USERNAME,
        password=_KC_ALICE_PASSWORD,
    )


@pytest.fixture(scope="session")
def bob_token(kc_url: str) -> str:
    """RS256 token for bob — seeded org-b viewer."""
    return _fetch_token_or_skip(
        keycloak_url=kc_url,
        realm=_KC_REALM,
        client_id=_KC_CLIENT_ID,
        client_secret=_KC_CLIENT_SECRET,
        grant_type="password",
        username=_KC_BOB_USERNAME,
        password=_KC_BOB_PASSWORD,
    )
