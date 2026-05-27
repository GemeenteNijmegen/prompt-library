import logging

import httpx
from jose import jwt as jose_jwt

from src.config import settings

_log = logging.getLogger(__name__)


class KeycloakError(Exception):
    pass


class KeycloakClient:
    """Thin wrapper around the Keycloak token and admin APIs for API-key issuance.

    In tests, replace the instance bound to the dependency with a mock.
    In production, KEYCLOAK_URL, KEYCLOAK_API_KEY_CLIENT_*, and
    KEYCLOAK_ADMIN_CLIENT_* must be configured.
    """

    def _token_url(self) -> str:
        base = settings.KEYCLOAK_URL.rstrip("/")
        return f"{base}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"

    def _admin_base(self) -> str:
        base = settings.KEYCLOAK_URL.rstrip("/")
        return f"{base}/admin/realms/{settings.KEYCLOAK_REALM}"

    def issue_offline_token(self, user_access_token: str) -> tuple[str, str]:
        """Exchange a user access token for a Keycloak offline token.

        Returns ``(offline_token, session_id)`` where ``offline_token`` is the
        raw JWT to hand back to the caller exactly once, and ``session_id`` is
        the Keycloak session identifier stored for later revocation.
        """
        resp = httpx.post(
            self._token_url(),
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "client_id": settings.KEYCLOAK_API_KEY_CLIENT_ID,
                "client_secret": settings.KEYCLOAK_API_KEY_CLIENT_SECRET,
                "subject_token": user_access_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "requested_token_type": "urn:ietf:params:oauth:token-type:refresh_token",
                "scope": "offline_access",
            },
            timeout=10.0,
        )
        if resp.status_code != 200:
            _log.warning("Keycloak token exchange failed status=%s", resp.status_code)
            raise KeycloakError(f"Keycloak token exchange failed: {resp.status_code}")

        data = resp.json()
        offline_token: str = data["refresh_token"]

        # Extract session_state without signature verification — we just
        # received this token from Keycloak so we trust its structure.
        claims = jose_jwt.get_unverified_claims(offline_token)
        session_id: str = claims.get("session_state") or claims.get("jti", "")
        return offline_token, session_id

    def _get_admin_token(self) -> str:
        resp = httpx.post(
            self._token_url(),
            data={
                "grant_type": "client_credentials",
                "client_id": settings.KEYCLOAK_ADMIN_CLIENT_ID,
                "client_secret": settings.KEYCLOAK_ADMIN_CLIENT_SECRET,
            },
            timeout=10.0,
        )
        if resp.status_code != 200:
            _log.warning("Keycloak admin token request failed status=%s", resp.status_code)
            raise KeycloakError(f"Keycloak admin token request failed: {resp.status_code}")
        return resp.json()["access_token"]

    def revoke_session(self, session_id: str) -> None:
        """Revoke a Keycloak session by its session ID."""
        admin_token = self._get_admin_token()
        resp = httpx.delete(
            f"{self._admin_base()}/sessions/{session_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10.0,
        )
        # 204 = revoked, 404 = already gone — both are acceptable
        if resp.status_code not in (204, 404):
            _log.warning("Keycloak session revocation failed status=%s", resp.status_code)
            raise KeycloakError(f"Keycloak session revocation failed: {resp.status_code}")

    def logout_all_sessions(self, user_external_id: str) -> None:
        """Invalidate all interactive sessions for a Keycloak user.

        ``user_external_id`` is the Keycloak user UUID (the ``sub`` claim).
        """
        admin_token = self._get_admin_token()
        resp = httpx.delete(
            f"{self._admin_base()}/users/{user_external_id}/sessions",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10.0,
        )
        # 204 = all sessions terminated, 404 = user not found (treat as no-op)
        if resp.status_code not in (204, 404):
            _log.warning(
                "Keycloak logout-all-sessions failed user=%s status=%s",
                user_external_id,
                resp.status_code,
            )
            raise KeycloakError(
                f"Keycloak logout-all-sessions failed: {resp.status_code}"
            )


_default_client = KeycloakClient()


def get_keycloak_client() -> KeycloakClient:
    return _default_client
