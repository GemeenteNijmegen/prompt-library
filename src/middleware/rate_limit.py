import time
from collections import defaultdict
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from src.utils.jwt_utils import decode_and_verify


class _InMemoryCounter:
    def __init__(self):
        self._counts: dict[tuple[str, int], int] = defaultdict(int)

    def _window(self) -> int:
        return int(time.time() // 60)

    def increment(self, key: str) -> int:
        bucket = (key, self._window())
        self._counts[bucket] += 1
        return self._counts[bucket]

    def reset(self, key: str) -> None:
        bucket = (key, self._window())
        self._counts[bucket] = 0


_RATE_LIMITED_RESPONSE = JSONResponse(
    status_code=429,
    content={"error": {"code": "RATE_LIMITED", "message": "Too many requests"}},
)

_TIER_ANONYMOUS = "anonymous"
_TIER_USER = "user"
_TIER_MACHINE = "machine"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        limit_anonymous: int = 30,
        limit_user: int = 120,
        limit_machine: int = 300,
    ):
        super().__init__(app)
        self._limit = {
            _TIER_ANONYMOUS: limit_anonymous,
            _TIER_USER: limit_user,
            _TIER_MACHINE: limit_machine,
        }
        self._counter = _InMemoryCounter()

    def _identify(self, request: Request) -> tuple[str, str]:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            ip = request.client.host if request.client else "unknown"
            return _TIER_ANONYMOUS, f"anon:{ip}"
        token = auth.split(" ", 1)[1]
        try:
            claims = decode_and_verify(token)
            sub = claims.get("sub", "unknown")
            if claims.get("token_type") == "machine":
                return _TIER_MACHINE, f"machine:{sub}"
            return _TIER_USER, f"user:{sub}"
        except Exception:
            ip = request.client.host if request.client else "unknown"
            return _TIER_ANONYMOUS, f"anon:{ip}"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        tier, key = self._identify(request)
        count = self._counter.increment(key)
        if count > self._limit[tier]:
            return _RATE_LIMITED_RESPONSE
        return await call_next(request)
