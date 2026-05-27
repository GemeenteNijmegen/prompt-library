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


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        limit_anonymous: int = 30,
        limit_user: int = 120,
        limit_azp: int = 600,
        limit_org: int = 1200,
    ):
        super().__init__(app)
        self._limit_anonymous = limit_anonymous
        self._limit_user = limit_user
        self._limit_azp = limit_azp
        self._limit_org = limit_org
        self._counter = _InMemoryCounter()

    def _identify(self, request: Request) -> list[tuple[str, int]]:
        """Return [(bucket_key, limit)] for every rate-limit axis that applies."""
        ip = request.client.host if request.client else "unknown"
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return [(f"anon:{ip}", self._limit_anonymous)]

        token = auth.split(" ", 1)[1]
        try:
            claims = decode_and_verify(token)
            sub = claims.get("sub", "unknown")
            azp = claims.get("azp", "")
            org_id = claims.get("org_id", "")

            buckets: list[tuple[str, int]] = [(f"user:{sub}", self._limit_user)]
            if azp:
                buckets.append((f"azp:{azp}", self._limit_azp))
            if org_id:
                buckets.append((f"org:{org_id}", self._limit_org))
            return buckets
        except Exception:
            return [(f"anon:{ip}", self._limit_anonymous)]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        for key, limit in self._identify(request):
            count = self._counter.increment(key)
            if count > limit:
                return _RATE_LIMITED_RESPONSE
        return await call_next(request)
