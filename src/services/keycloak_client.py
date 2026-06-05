import logging

import httpx

from src.config import settings

_log = logging.getLogger(__name__)


class KeycloakError(Exception):
    pass


class KeycloakClient:
    """Thin wrapper around the Keycloak admin API.

    Under the opaque-API-key model (ADR 0004 rev 2) the gallery no longer asks
    Keycloak to mint or revoke per-key tokens — keys are gallery-issued secrets.
    The only remaining Keycloak interaction is terminating a user's interactive
    SSO sessions for the logout-everywhere panic button, which uses the admin
    REST API.

    In tests, replace the instance bound to the dependency with a mock. In
    production, KEYCLOAK_URL and KEYCLOAK_ADMIN_CLIENT_* must be configured.
    """

    def _token_url(self) -> str:
        base = settings.KEYCLOAK_URL.rstrip("/")
        return f"{base}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"

    def _admin_base(self) -> str:
        base = settings.KEYCLOAK_URL.rstrip("/")
        return f"{base}/admin/realms/{settings.KEYCLOAK_REALM}"

    def _get_admin_token(self) -> str:
        try:
            resp = httpx.post(
                self._token_url(),
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.KEYCLOAK_ADMIN_CLIENT_ID,
                    "client_secret": settings.KEYCLOAK_ADMIN_CLIENT_SECRET,
                },
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            _log.warning("Keycloak admin token request failed: %s", exc)
            raise KeycloakError(f"Keycloak unreachable: {exc}") from exc
        if resp.status_code != 200:
            _log.warning("Keycloak admin token request failed status=%s", resp.status_code)
            raise KeycloakError(f"Keycloak admin token request failed: {resp.status_code}")
        return resp.json()["access_token"]

    def logout_all_sessions(self, user_external_id: str) -> None:
        """Invalidate all interactive sessions for a Keycloak user.

        ``user_external_id`` is the Keycloak user UUID (the ``sub`` claim).
        """
        admin_token = self._get_admin_token()
        try:
            resp = httpx.delete(
                f"{self._admin_base()}/users/{user_external_id}/sessions",
                headers={"Authorization": f"Bearer {admin_token}"},
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            _log.warning("Keycloak logout-all-sessions request failed user=%s: %s", user_external_id, exc)
            raise KeycloakError(f"Keycloak unreachable: {exc}") from exc
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
