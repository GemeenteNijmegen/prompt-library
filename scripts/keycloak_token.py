#!/usr/bin/env python3
"""Fetch a real RS256 access token from a local Keycloak instance.

Supports two grant types:
  password          – resource owner password credentials (requires --username/--password)
  client_credentials – service-account token (default; works with gallery-test-client)

Usage:
    python scripts/keycloak_token.py
    python scripts/keycloak_token.py --grant password --username devuser --password devpass
    KEYCLOAK_URL=http://localhost:8080 python scripts/keycloak_token.py
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


_DEFAULT_KC_URL = "http://localhost:8080"
_DEFAULT_REALM = "gallery"
_DEFAULT_CLIENT_ID = "gallery-test-client"
_DEFAULT_CLIENT_SECRET = "test-client-secret"


def fetch_token(
    keycloak_url: str,
    realm: str,
    client_id: str,
    client_secret: str,
    grant_type: str,
    username: str | None = None,
    password: str | None = None,
) -> str:
    import httpx

    token_url = f"{keycloak_url.rstrip('/')}/realms/{realm}/protocol/openid-connect/token"
    data: dict = {
        "grant_type": grant_type,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if grant_type == "password":
        if not username or not password:
            raise ValueError("--username and --password are required for password grant")
        data["username"] = username
        data["password"] = password

    resp = httpx.post(token_url, data=data, timeout=10.0)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Keycloak token request failed: {resp.status_code}\n{resp.text}"
        )
    return resp.json()["access_token"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch a Keycloak RS256 access token.")
    parser.add_argument(
        "--keycloak-url",
        default=os.environ.get("KEYCLOAK_URL", _DEFAULT_KC_URL),
        help=f"Keycloak base URL (default: {_DEFAULT_KC_URL})",
    )
    parser.add_argument(
        "--realm",
        default=os.environ.get("KEYCLOAK_REALM", _DEFAULT_REALM),
        help=f"Realm name (default: {_DEFAULT_REALM})",
    )
    parser.add_argument(
        "--client-id",
        default=os.environ.get("KEYCLOAK_TEST_CLIENT_ID", _DEFAULT_CLIENT_ID),
        help=f"Client ID (default: {_DEFAULT_CLIENT_ID})",
    )
    parser.add_argument(
        "--client-secret",
        default=os.environ.get("KEYCLOAK_TEST_CLIENT_SECRET", _DEFAULT_CLIENT_SECRET),
        help="Client secret",
    )
    parser.add_argument(
        "--grant",
        choices=["client_credentials", "password"],
        default="client_credentials",
        help="Grant type (default: client_credentials)",
    )
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    args = parser.parse_args()

    try:
        token = fetch_token(
            keycloak_url=args.keycloak_url,
            realm=args.realm,
            client_id=args.client_id,
            client_secret=args.client_secret,
            grant_type=args.grant,
            username=args.username,
            password=args.password,
        )
        print(token)
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
