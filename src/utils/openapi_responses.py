"""Reusable OpenAPI response declarations for the shared error envelope.

Every API error is returned as ``{"error": {"code", "message"}}`` (see
``src/utils/error.py`` and ``ErrorResponse`` in ``src/schemas/common.py``).
Routes spread these constants into their ``responses=`` argument so the
generated spec advertises the failure modes a client must handle — in
particular the ``401``/``403`` the auth layer raises, which FastAPI does not
document on its own.
"""
from src.schemas.common import ErrorResponse

UNAUTHORIZED = {401: {"model": ErrorResponse, "description": "Missing or invalid credentials"}}
FORBIDDEN = {403: {"model": ErrorResponse, "description": "Insufficient scope or not the resource owner"}}
NOT_FOUND = {404: {"model": ErrorResponse, "description": "Resource not found"}}
CONFLICT = {409: {"model": ErrorResponse, "description": "Conflicts with existing state"}}

# Marker for endpoints that personalise results when a token is present but
# remain fully usable anonymously. OpenAPI expresses "auth optional" as an empty
# requirement object listed alongside the scheme, but FastAPI deep-merges
# ``openapi_extra`` into the auto-generated ``security`` list rather than
# replacing it. So routes tag themselves with this marker and the custom
# ``openapi()`` builder in ``src/main.py`` rewrites their security cleanly.
OPTIONAL_AUTH_MARKER = "x-optional-auth"
OPTIONAL_AUTH = {OPTIONAL_AUTH_MARKER: True}
