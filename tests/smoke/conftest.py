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

_stack_live = bool(KEYCLOAK_URL and GALLERY_API_URL)

skip_if_no_stack = pytest.mark.skipif(
    not _stack_live,
    reason="Set KEYCLOAK_URL and GALLERY_API_URL to run smoke tests",
)


@pytest.fixture(scope="session")
def kc_url() -> str:
    return KEYCLOAK_URL.rstrip("/")


@pytest.fixture(scope="session")
def api_url() -> str:
    return GALLERY_API_URL.rstrip("/")


@pytest.fixture(scope="session")
def rs256_token(kc_url: str) -> str:
    """Fetch a real RS256 access token from Keycloak via client-credentials grant."""
    from scripts.keycloak_token import fetch_token
    return fetch_token(
        keycloak_url=kc_url,
        realm=_KC_REALM,
        client_id=_KC_CLIENT_ID,
        client_secret=_KC_CLIENT_SECRET,
        grant_type="client_credentials",
    )


@pytest.fixture(scope="session")
def rs256_user_token(kc_url: str) -> str:
    """Fetch a real RS256 access token via resource-owner password grant."""
    from scripts.keycloak_token import fetch_token
    return fetch_token(
        keycloak_url=kc_url,
        realm=_KC_REALM,
        client_id=_KC_CLIENT_ID,
        client_secret=_KC_CLIENT_SECRET,
        grant_type="password",
        username=_KC_USERNAME,
        password=_KC_PASSWORD,
    )
