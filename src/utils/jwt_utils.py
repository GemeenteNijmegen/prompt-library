import logging
import time
from typing import Any

import httpx
from cachetools import TTLCache
from jose import ExpiredSignatureError, JWTError, jwt
from jose.exceptions import JWTClaimsError

from src.config import settings

_log = logging.getLogger(__name__)

_jwks_cache: TTLCache = TTLCache(maxsize=1, ttl=300)
_stale_jwks: dict | None = None


class JWTExpiredError(Exception):
    pass


class JWTInvalidError(Exception):
    pass


class JWTConfigError(Exception):
    pass


def _get_jwks_cache() -> TTLCache:
    global _jwks_cache
    ttl = settings.JWKS_CACHE_TTL_SECONDS
    if _jwks_cache.ttl != ttl:
        _jwks_cache = TTLCache(maxsize=1, ttl=ttl)
    return _jwks_cache


def _fetch_jwks() -> dict:
    global _stale_jwks
    cache = _get_jwks_cache()
    cached = cache.get("jwks")
    if cached is not None:
        return cached
    try:
        resp = httpx.get(settings.JWKS_URI, timeout=10)
        resp.raise_for_status()
        jwks = resp.json()
        cache["jwks"] = jwks
        _stale_jwks = jwks
        return jwks
    except Exception:
        if _stale_jwks is not None:
            _log.warning("Keycloak unreachable; serving stale JWKS (kid set may be outdated)")
            return _stale_jwks
        raise


def _decode_with_jwks(token: str, jwks: dict) -> dict[str, Any]:
    return jwt.decode(
        token,
        jwks,
        algorithms=["RS256"],  # JWKS path only — never allow HS256 here (algorithm confusion attack)
        issuer=settings.JWT_ISSUER or None,
        audience=settings.JWT_AUDIENCE or None,
        options={"leeway": settings.JWT_LEEWAY_SECONDS},
    )


def decode_and_verify(token: str) -> dict[str, Any]:
    if settings.JWKS_URI:
        try:
            jwks = _fetch_jwks()
            try:
                claims = _decode_with_jwks(token, jwks)
            except ExpiredSignatureError:
                raise
            except (JWTError, JWTClaimsError):
                # Unknown kid or key rotation — invalidate cache and retry once.
                _get_jwks_cache().clear()
                jwks = _fetch_jwks()
                claims = _decode_with_jwks(token, jwks)
        except ExpiredSignatureError:
            raise JWTExpiredError("Token has expired")
        except (JWTError, JWTClaimsError) as exc:
            raise JWTInvalidError(str(exc)) from exc
        return claims

    # HMAC dev fallback
    if not settings.JWT_SECRET_KEY:
        raise JWTConfigError("No JWKS_URI and no JWT_SECRET_KEY configured")

    if settings.ENVIRONMENT == "production":
        raise JWTConfigError("HMAC dev fallback is not allowed in production")

    try:
        claims = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=["HS256"],  # HMAC only — never allow RS256 here (algorithm confusion attack)
            issuer=settings.JWT_ISSUER or None,
            audience=settings.JWT_AUDIENCE or None,
            options={"leeway": settings.JWT_LEEWAY_SECONDS},
        )
    except ExpiredSignatureError:
        raise JWTExpiredError("Token has expired")
    except (JWTError, JWTClaimsError) as exc:
        raise JWTInvalidError(str(exc)) from exc

    return claims
