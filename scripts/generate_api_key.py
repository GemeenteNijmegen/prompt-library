#!/usr/bin/env python3
"""Mint a new gallery API key (pg_...) via POST /api/v1/me/api-keys.

Requires a bearer token from an OAuth/JWT session (not another API key) — API
keys cannot be used to create other API keys — and the caller must hold the
`apikey:create` scope.

Two flows, pick based on who/what the key is for:

  Machine token for a bot/chat-client/CI pipeline (ADR 0004 "service-identity
  keys for headless users"): have a Gallery Operator create a local,
  non-federated Keycloak user for that service identity and grant it the
  scopes it needs, then use --username with the password grant below. Fully
  non-interactive — no browser, no devtools, scriptable in CI.

  Never pass the password as a bare --password value on an interactive shell —
  it lands in shell history and is visible to other users on the box via `ps`.
  Prefer, in order:
    1. $GALLERY_PASSWORD env var (a CI secret store injects this, not argv)
    2. the hidden getpass prompt (omit --password with --username; nothing
       touches history or argv)
    3. --password only when the caller is itself a non-interactive script
       receiving the secret through a mechanism that never shells out

      GALLERY_PASSWORD="$SVC_PASSWORD" python scripts/generate_api_key.py \\
          --label "acme-chatbot" --username svc-acme-chatbot

  Personal key for a human: the default when neither --username nor --token is
  given. Opens your system browser to Keycloak's login page via the
  authorization-code + PKCE flow (against the pre-registered public loopback
  client `mcp-client`), catches the redirect on a local loopback HTTP server,
  and exchanges it for a token — no devtools, no copy-pasting.

      python scripts/generate_api_key.py --label "my laptop"

  If a browser can't be opened from where this runs (headless box, no
  display) or the loopback port can't be bound, fall back to --paste-token
  for the old manual devtools flow (Network tab -> any API call ->
  Authorization header).

Usage:
    # Machine/service-identity token (headless Keycloak user, no browser).
    # Password via env var — never on argv.
    GALLERY_PASSWORD="$SVC_PASSWORD" python scripts/generate_api_key.py \\
        --label "acme-chatbot" --username svc-acme-chatbot

    # Same, but typed interactively (hidden input, nothing in history/argv)
    python scripts/generate_api_key.py --label "acme-chatbot" \\
        --username svc-acme-chatbot

    # Local dev shortcut using the seeded gallery-test-client password grant
    GALLERY_PASSWORD=devpass python scripts/generate_api_key.py \\
        --label "my key" --username devuser

    # Against a deployed instance
    GALLERY_PASSWORD="$SVC_PASSWORD" python scripts/generate_api_key.py \\
        --label "laptop" \\
        --base-url https://prompts.ai.sandbox-01.csp-nijmegen.nl \\
        --keycloak-url https://<sandbox-keycloak-host> --realm gallery \\
        --username svc-acme-chatbot

    # Bring your own token (e.g. already fetched via keycloak_token.py)
    python scripts/generate_api_key.py --token "$TOKEN" --label "my key"

    # Devtools fallback: prints a login URL, prompts you to paste a token
    # grabbed from browser dev tools. Use only when the browser/loopback flow
    # above can't run from where you are (headless box, no display, no free
    # loopback port) — not for machine/service tokens.
    python scripts/generate_api_key.py --label "my key" --paste-token
"""
import argparse
import base64
import getpass
import hashlib
import http.server
import os
import secrets
import sys
import urllib.parse
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.keycloak_token import fetch_token

_DEFAULT_BASE_URL = "http://localhost:8000"
_DEFAULT_LOOPBACK_CLIENT_ID = "mcp-client"
_DEFAULT_LOOPBACK_PORT = 6274
_DEFAULT_LOOPBACK_SCOPE = "openid apikey:create"


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Catches exactly one OAuth redirect and stashes the result on the server."""

    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        self.server.auth_code = params.get("code", [None])[0]
        self.server.auth_state = params.get("state", [None])[0]
        self.server.auth_error = (params.get("error_description") or params.get("error") or [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if self.server.auth_code:
            body = "<html><body><h3>Login complete.</h3>You can close this tab and return to the terminal.</body></html>"
        else:
            body = f"<html><body><h3>Login failed.</h3>{self.server.auth_error or 'No authorization code received.'}</body></html>"
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format, *args):
        pass  # silence default per-request access logging


def browser_login(keycloak_url: str, realm: str, client_id: str, port: int, scope: str) -> str:
    """Authorization-code + PKCE flow via a local loopback redirect — no devtools.

    Requires a public client already registered on the realm with
    ``http://127.0.0.1:<port>/*`` (or equivalent) in its redirect URIs — e.g.
    the pre-registered ``mcp-client`` (keycloak/templates/mcp-public-client.json).
    """
    import httpx

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    state = secrets.token_urlsafe(16)
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    auth_url = f"{keycloak_url.rstrip('/')}/realms/{realm}/protocol/openid-connect/auth?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )

    try:
        server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    except OSError as exc:
        raise RuntimeError(
            f"Could not bind the loopback callback server on 127.0.0.1:{port} ({exc}). "
            f"Only port {_DEFAULT_LOOPBACK_PORT} is registered as a redirect URI for "
            f"'{client_id}', so there's no alternate port to try — free it and retry, "
            "or fall back to --paste-token."
        ) from exc
    server.timeout = 300
    server.auth_code = None
    server.auth_state = None
    server.auth_error = None

    print(f"Opening your browser to log in...\n  {auth_url}\n", file=sys.stderr)
    if not webbrowser.open(auth_url):
        print("Could not open a browser automatically — open the URL above manually.", file=sys.stderr)

    try:
        server.handle_request()
    finally:
        server.server_close()

    if server.auth_code is None:
        raise RuntimeError(
            f"Browser login failed or timed out after {server.timeout}s: "
            f"{server.auth_error or 'no callback received'}. Retry, or fall back to --paste-token."
        )
    if server.auth_state != state:
        raise RuntimeError("OAuth state mismatch on the callback — possible CSRF, aborting.")

    resp = httpx.post(
        f"{keycloak_url.rstrip('/')}/realms/{realm}/protocol/openid-connect/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code": server.auth_code,
            "code_verifier": verifier,
        },
        timeout=10.0,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Token exchange failed: {resp.status_code}\n{resp.text}")
    return resp.json()["access_token"]


def prompt_for_token(keycloak_url: str, realm: str, base_url: str) -> str:
    login_url = f"{keycloak_url.rstrip('/')}/realms/{realm}/account/"
    print(
        "--paste-token: manual devtools fallback. If this key is for a bot/chat-client/"
        "CI pipeline rather than you personally, use --username (with $GALLERY_PASSWORD "
        "or the hidden prompt) against a dedicated headless Keycloak user instead (see "
        "the script's module docstring).\n\n"
        "Log in, then grab your bearer token (browser dev tools -> Network -> any "
        "API call -> Authorization header) and paste it below.\n"
        f"  Keycloak: {login_url}\n"
        f"  App:      {base_url}\n",
        file=sys.stderr,
    )
    token = input("Paste bearer token: ").strip()
    if not token:
        raise RuntimeError("No token provided.")
    return token


def create_api_key(base_url: str, token: str, label: str) -> dict:
    import httpx

    resp = httpx.post(
        f"{base_url.rstrip('/')}/api/v1/me/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"label": label},
        timeout=10.0,
    )
    if resp.status_code != 201:
        raise RuntimeError(f"API key creation failed: {resp.status_code}\n{resp.text}")
    return resp.json()["data"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a new gallery API key.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("GALLERY_BASE_URL", _DEFAULT_BASE_URL),
        help=f"Gallery base URL (default: {_DEFAULT_BASE_URL})",
    )
    parser.add_argument("--label", required=True, help="Label for the new key")
    parser.add_argument(
        "--token",
        default=os.environ.get("TOKEN"),
        help="Existing interactive bearer token (or set $TOKEN). Skips the login prompt entirely.",
    )

    # Keycloak options (used to build the login URL, and for password grant below).
    parser.add_argument("--keycloak-url", default=os.environ.get("KEYCLOAK_URL", "http://localhost:8080"))
    parser.add_argument("--realm", default=os.environ.get("KEYCLOAK_REALM", "gallery"))

    # Password-grant options: the non-interactive path. Use a dedicated headless
    # Keycloak user for machine/service tokens (ADR 0004), or a seeded dev user
    # (e.g. devuser/devpass) for local dev. Skips the browser login prompt.
    parser.add_argument(
        "--username",
        default=None,
        help="Use password grant instead of the interactive login prompt. Pair with "
        "$GALLERY_PASSWORD (preferred) or omit --password to be prompted for it hidden. "
        "Use a dedicated headless Keycloak user for machine/bot tokens.",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("GALLERY_PASSWORD"),
        help="Discouraged: visible in shell history and to other users via `ps`. "
        "Prefer $GALLERY_PASSWORD, or omit both to be prompted (hidden input).",
    )
    parser.add_argument(
        "--password-client-id", default=os.environ.get("KEYCLOAK_TEST_CLIENT_ID", "gallery-test-client")
    )
    parser.add_argument(
        "--password-client-secret", default=os.environ.get("KEYCLOAK_TEST_CLIENT_SECRET", "test-client-secret")
    )

    # Browser loopback options: the default interactive path (authorization-code +
    # PKCE against a pre-registered public loopback client). See --paste-token for
    # the manual devtools fallback.
    parser.add_argument(
        "--loopback-client-id",
        default=os.environ.get("KEYCLOAK_LOOPBACK_CLIENT_ID", _DEFAULT_LOOPBACK_CLIENT_ID),
        help=f"Public loopback OAuth client to log in with (default: {_DEFAULT_LOOPBACK_CLIENT_ID})",
    )
    parser.add_argument(
        "--callback-port",
        type=int,
        default=int(os.environ.get("KEYCLOAK_LOOPBACK_PORT", _DEFAULT_LOOPBACK_PORT)),
        help=f"Local port for the OAuth redirect callback (default: {_DEFAULT_LOOPBACK_PORT}); "
        "must match a redirect URI registered on --loopback-client-id.",
    )
    parser.add_argument(
        "--scope",
        default=_DEFAULT_LOOPBACK_SCOPE,
        help=f"OAuth scopes to request in the browser flow (default: '{_DEFAULT_LOOPBACK_SCOPE}', matching "
        f"{_DEFAULT_LOOPBACK_CLIENT_ID}'s assigned client scopes). Requesting a scope not assigned to "
        "--loopback-client-id in Keycloak fails with 'Invalid scopes' — adjust this if you pass a "
        "different --loopback-client-id.",
    )
    parser.add_argument(
        "--paste-token",
        action="store_true",
        help="Skip the browser/loopback flow and fall back to the manual devtools paste prompt.",
    )

    args = parser.parse_args()

    try:
        token = args.token
        if not token and args.username:
            password = args.password or getpass.getpass(f"Password for {args.username}: ")
            if not password:
                raise RuntimeError("No password provided.")
            token = fetch_token(
                keycloak_url=args.keycloak_url,
                realm=args.realm,
                client_id=args.password_client_id,
                client_secret=args.password_client_secret,
                grant_type="password",
                username=args.username,
                password=password,
            )
        if not token and args.paste_token:
            token = prompt_for_token(args.keycloak_url, args.realm, args.base_url)
        if not token:
            token = browser_login(
                args.keycloak_url, args.realm, args.loopback_client_id, args.callback_port, args.scope
            )

        result = create_api_key(args.base_url, token, args.label)
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"token:       {result['token']}")
    print(f"id:          {result['id']}")
    print(f"label:       {result['label']}")
    print(f"prefix:      {result['token_prefix']}")
    print(f"scopes:      {' '.join(result['scopes'])}")
    print(f"expires_at:  {result['expires_at']}")


if __name__ == "__main__":
    main()
