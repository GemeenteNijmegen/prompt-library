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

# Raw Authorization header value for the current request — set by
# _CaptureAuthorizationMiddleware before the tool is called.
_authorization: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_authorization", default=None
)


class _CaptureAuthorizationMiddleware:
    """ASGI middleware that copies the raw Authorization header into a context var.

    No validation, no decoding — the value is forwarded verbatim to the gallery.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            auth_value: str | None = None
            for name, value in scope.get("headers", []):
                if name.lower() == b"authorization":
                    auth_value = value.decode()
                    break
            token = _authorization.set(auth_value)
            try:
                await self._app(scope, receive, send)
            finally:
                _authorization.reset(token)
        else:
            await self._app(scope, receive, send)


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
        response.raise_for_status()

    return response.json()


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def build_app() -> ASGIApp:
    """Return the ASGI app with the auth-capture middleware applied."""
    app: ASGIApp = _CaptureAuthorizationMiddleware(mcp.streamable_http_app())
    return CORSMiddleware(
        app,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["mcp-session-id"],
    )
