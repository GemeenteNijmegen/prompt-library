"""
Token-forwarding MCP sidecar for the Prompt Gallery (ADR 0005).

Design invariant: this module holds ZERO authorization logic.  The caller's
bearer token (JWT or pg_… API key) is captured from the incoming HTTP
Authorization header and forwarded unchanged to the gallery REST API.  The
gallery is the single enforcement point for visibility and scope.
"""
import contextvars
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from gallery_mcp.config import settings

# Raw Authorization header value for the current request.
_authorization: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_authorization", default=None
)

# Set to True by search_prompts when the gallery returns 401 — signals the
# _AuthMiddleware to translate the FastMCP response to a spec-shaped HTTP 401.
_gallery_auth_failed: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_gallery_auth_failed", default=False
)

# Paths that must not require an Authorization header.
_PUBLIC_PATHS: frozenset[str] = frozenset(
    {"/.well-known/oauth-protected-resource", "/health"}
)


def _www_authenticate_value() -> str:
    url = f"{settings.MCP_RESOURCE_URL}/.well-known/oauth-protected-resource"
    return f'Bearer resource_metadata="{url}"'


class _AuthMiddleware:
    """Single middleware for auth capture, missing-auth 401, and gallery-401 translation.

    Three responsibilities (all crypto-free, ADR 0005 invariant preserved):
    1. Copies the raw Authorization header into ``_authorization`` for tool use.
    2. Intercepts requests to protected endpoints with no Authorization header and
       returns HTTP 401 + WWW-Authenticate before FastMCP sees the request.
    3. Wraps ``send`` to detect when the tool set ``_gallery_auth_failed`` and
       upgrades the FastMCP HTTP 200 JSON-RPC error into an HTTP 401 + WWW-Authenticate.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        auth_value: str | None = None
        for name, value in scope.get("headers", []):
            if name.lower() == b"authorization":
                auth_value = value.decode()
                break

        path = scope.get("path", "")

        if path not in _PUBLIC_PATHS and auth_value is None:
            await self._send_401(send)
            return

        auth_token = _authorization.set(auth_value)
        failed_token = _gallery_auth_failed.set(False)
        try:
            await self._app(scope, receive, self._patched_send(send))
        finally:
            _authorization.reset(auth_token)
            _gallery_auth_failed.reset(failed_token)

    def _patched_send(self, send: Send):
        async def _send(message) -> None:
            if (
                message["type"] == "http.response.start"
                and _gallery_auth_failed.get()
            ):
                www = _www_authenticate_value().encode()
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() != b"www-authenticate"
                ]
                headers.append((b"www-authenticate", www))
                message = {**message, "status": 401, "headers": headers}
            await send(message)

        return _send

    async def _send_401(self, send: Send) -> None:
        www = _www_authenticate_value().encode()
        body = b'{"error":"unauthorized"}'
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", www),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})


mcp = FastMCP("Prompt Gallery", stateless_http=True, json_response=True)


@mcp.tool()
async def search_prompts(
    query: str | None = None,
    page: int = 1,
    per_page: int = 20,
    category_id: int | None = None,
    tag: str | None = None,
    featured: bool | None = None,
) -> dict[str, Any]:
    """Search and list prompts from the gallery.

    Row-level visibility (draft / published_org / published_public) is enforced
    by the gallery — the sidecar cannot return a prompt the gallery would withhold.

    Args:
        query: Free-text search string (passed as `search` to the gallery).
        page: 1-based page number (default 1).
        per_page: Results per page, 1–100 (default 20).
        category_id: Filter by category ID.
        tag: Filter by tag name.
        featured: If true, return only featured prompts.
    """
    auth = _authorization.get()
    if not auth:
        raise ValueError(
            "Missing Authorization header — the caller must provide a bearer token or pg_… API key."
        )

    params: dict[str, Any] = {"page": page, "per_page": per_page}
    if query is not None:
        params["search"] = query
    if category_id is not None:
        params["category_id"] = category_id
    if tag is not None:
        params["tag"] = tag
    if featured is not None:
        params["featured"] = str(featured).lower()

    async with httpx.AsyncClient(timeout=settings.GALLERY_REQUEST_TIMEOUT) as client:
        response = await client.get(
            f"{settings.GALLERY_API_URL}/api/v1/prompts",
            params=params,
            headers={"Authorization": auth},
        )
        if response.status_code == 401:
            _gallery_auth_failed.set(True)
        response.raise_for_status()

    return response.json()


@mcp.tool()
async def get_prompt(prompt_id: int) -> dict[str, Any]:
    """Fetch full details for a single prompt, including prompt_text and example_output.

    Use this after search_prompts to retrieve the complete text of a prompt the
    caller has permission to view. Visibility is enforced by the gallery.

    Args:
        prompt_id: Numeric prompt ID returned by search_prompts.
    """
    auth = _authorization.get()
    if not auth:
        raise ValueError(
            "Missing Authorization header — the caller must provide a bearer token or pg_… API key."
        )

    async with httpx.AsyncClient(timeout=settings.GALLERY_REQUEST_TIMEOUT) as client:
        response = await client.get(
            f"{settings.GALLERY_API_URL}/api/v1/prompts/{prompt_id}",
            headers={"Authorization": auth},
        )
        if response.status_code == 401:
            _gallery_auth_failed.set(True)
        response.raise_for_status()

    return response.json()


@mcp.tool()
async def list_featured() -> dict[str, Any]:
    """Return the curated list of featured prompts.

    Args: none
    """
    auth = _authorization.get()
    if not auth:
        raise ValueError(
            "Missing Authorization header — the caller must provide a bearer token or pg_… API key."
        )

    async with httpx.AsyncClient(timeout=settings.GALLERY_REQUEST_TIMEOUT) as client:
        response = await client.get(
            f"{settings.GALLERY_API_URL}/api/v1/prompts/featured",
            headers={"Authorization": auth},
        )
        if response.status_code == 401:
            _gallery_auth_failed.set(True)
        response.raise_for_status()

    return response.json()


@mcp.tool()
async def list_categories() -> dict[str, Any]:
    """Return all prompt categories available in the gallery.

    Use the returned category IDs with search_prompts(category_id=…).

    Args: none
    """
    auth = _authorization.get()
    if not auth:
        raise ValueError(
            "Missing Authorization header — the caller must provide a bearer token or pg_… API key."
        )

    async with httpx.AsyncClient(timeout=settings.GALLERY_REQUEST_TIMEOUT) as client:
        response = await client.get(
            f"{settings.GALLERY_API_URL}/api/v1/categories",
            headers={"Authorization": auth},
        )
        if response.status_code == 401:
            _gallery_auth_failed.set(True)
        response.raise_for_status()

    return response.json()


@mcp.tool()
async def list_tags() -> dict[str, Any]:
    """Return all tags in the gallery.

    Use the returned tag names with search_prompts(tag=…).

    Args: none
    """
    auth = _authorization.get()
    if not auth:
        raise ValueError(
            "Missing Authorization header — the caller must provide a bearer token or pg_… API key."
        )

    async with httpx.AsyncClient(timeout=settings.GALLERY_REQUEST_TIMEOUT) as client:
        response = await client.get(
            f"{settings.GALLERY_API_URL}/api/v1/tags",
            headers={"Authorization": auth},
        )
        if response.status_code == 401:
            _gallery_auth_failed.set(True)
        response.raise_for_status()

    return response.json()


@mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
async def oauth_protected_resource(request: Request) -> JSONResponse:
    """RFC 9728 protected-resource metadata for OAuth client discovery."""
    return JSONResponse(
        {
            "resource": settings.MCP_RESOURCE_URL,
            "authorization_servers": [settings.KEYCLOAK_REALM_URL],
            "bearer_methods_supported": ["header"],
        }
    )


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def build_app() -> ASGIApp:
    """Return the ASGI app with auth middleware and CORS applied."""
    app: ASGIApp = _AuthMiddleware(mcp.streamable_http_app())
    return CORSMiddleware(
        app,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["mcp-session-id"],
    )
