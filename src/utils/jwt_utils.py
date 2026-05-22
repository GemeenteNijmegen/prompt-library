import time
from typing import Any

import httpx
from cachetools import TTLCache
from jose import ExpiredSignatureError, JWTError, jwt
from jose.exceptions import JWTClaimsError

from src.config import settings

_jwks_cache: TTLCache = TTLCache(maxsize=1, ttl=300)


class JWTExpiredError(Exception):
    pass


class JWTInvalidError(Exception):
    pass


class JWTConfigError(Exception):
    pass


def _fetch_jwks() -> dict:
    cached = _jwks_cache.get("jwks")
    if cached is not None:
        return cached
    resp = httpx.get(settings.JWKS_URI, timeout=10)
    resp.raise_for_status()
    jwks = resp.json()
    _jwks_cache["jwks"] = jwks
    return jwks


def decode_and_verify(token: str) -> dict[str, Any]:
    if settings.JWKS_URI:
        try:
            jwks = _fetch_jwks()
            claims = jwt.decode(
                token,
                jwks,
                algorithms=["RS256"],
                issuer=settings.JWT_ISSUER or None,
                options={"verify_aud": False},
            )
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
            algorithms=["HS256"],
            issuer=settings.JWT_ISSUER or None,
            options={"verify_aud": False},
        )
    except ExpiredSignatureError:
        raise JWTExpiredError("Token has expired")
    except (JWTError, JWTClaimsError) as exc:
        raise JWTInvalidError(str(exc)) from exc

    return claims
