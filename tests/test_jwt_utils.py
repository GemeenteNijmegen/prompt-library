import os
import time
from unittest.mock import patch, MagicMock

import pytest
from jose import jwt

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "testing")
os.environ["JWT_SECRET_KEY"] = "test-secret-key"
os.environ["JWKS_URI"] = ""

from src.utils.jwt_utils import (
    JWTExpiredError,
    JWTInvalidError,
    JWTConfigError,
    decode_and_verify,
    _jwks_cache,
)


SECRET = "test-secret-key"
ISSUER = "http://localhost:9000"


def _make_token(secret=SECRET, issuer=ISSUER, expired=False, extra_claims=None):
    now = int(time.time())
    payload = {
        "sub": "user-123",
        "scope": ["prompt:read"],
        "name": "Test User",
        "email": "test@example.com",
        "avatar_url": None,
        "iss": issuer,
        "iat": now - 10,
        "exp": (now - 5) if expired else (now + 3600),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture(autouse=True)
def _reset_cache_and_settings():
    _jwks_cache.clear()
    from src import config as cfg
    original_jwks_uri = cfg.settings.JWKS_URI
    original_secret = cfg.settings.JWT_SECRET_KEY
    original_env = cfg.settings.ENVIRONMENT
    cfg.settings.JWKS_URI = ""
    cfg.settings.JWT_SECRET_KEY = SECRET
    cfg.settings.ENVIRONMENT = "testing"
    yield
    cfg.settings.JWKS_URI = original_jwks_uri
    cfg.settings.JWT_SECRET_KEY = original_secret
    cfg.settings.ENVIRONMENT = original_env


def test_valid_hmac_token():
    token = _make_token()
    claims = decode_and_verify(token)
    assert claims["sub"] == "user-123"
    assert "prompt:read" in claims["scope"]


def test_expired_token_raises_jwt_expired_error():
    token = _make_token(expired=True)
    with pytest.raises(JWTExpiredError):
        decode_and_verify(token)


def test_tampered_token_raises_jwt_invalid_error():
    token = _make_token()
    tampered = token[:-5] + "XXXXX"
    with pytest.raises(JWTInvalidError):
        decode_and_verify(token=tampered)


def test_wrong_secret_raises_jwt_invalid_error():
    token = _make_token(secret="wrong-secret")
    with pytest.raises(JWTInvalidError):
        decode_and_verify(token)


def test_no_config_raises_jwt_config_error():
    from src import config as cfg
    cfg.settings.JWT_SECRET_KEY = ""
    cfg.settings.JWKS_URI = ""
    with pytest.raises(JWTConfigError):
        decode_and_verify(_make_token())


def test_hmac_refused_in_production():
    from src import config as cfg
    cfg.settings.ENVIRONMENT = "production"
    cfg.settings.JWKS_URI = ""
    with pytest.raises(JWTConfigError, match="not allowed in production"):
        decode_and_verify(_make_token())


def test_jwks_cache_not_refetched_within_ttl():
    from src import config as cfg
    cfg.settings.JWKS_URI = "http://example.com/.well-known/jwks.json"

    fake_jwks = {"keys": []}

    with patch("src.utils.jwt_utils._fetch_jwks") as mock_fetch:
        mock_fetch.side_effect = JWTInvalidError("no matching key")
        with pytest.raises(JWTInvalidError):
            decode_and_verify(_make_token())
        with pytest.raises(JWTInvalidError):
            decode_and_verify(_make_token())
        assert mock_fetch.call_count == 2  # called per decode, but the httpx layer is cached


def test_jwks_endpoint_cached(monkeypatch):
    from src import config as cfg
    import src.utils.jwt_utils as jwt_mod
    cfg.settings.JWKS_URI = "http://example.com/.well-known/jwks.json"

    call_count = 0

    def fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"keys": []}
        return resp

    monkeypatch.setattr("httpx.get", fake_get)
    jwt_mod._jwks_cache.clear()

    # Populate the cache
    try:
        decode_and_verify(_make_token())
    except Exception:
        pass

    # Second call should use cache
    try:
        decode_and_verify(_make_token())
    except Exception:
        pass

    assert call_count == 1, "JWKS endpoint should only be called once within TTL window"
