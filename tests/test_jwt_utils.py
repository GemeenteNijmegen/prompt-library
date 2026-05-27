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


AUDIENCE = "prompt-gallery-api"


def _make_token(secret=SECRET, issuer=ISSUER, audience=AUDIENCE, expired=False, extra_claims=None):
    now = int(time.time())
    payload = {
        "sub": "user-123",
        "aud": audience,
        "scope": ["prompt:read"],
        "name": "Test User",
        "email": "test@example.com",
        "avatar_url": None,
        "iss": issuer,
        "iat": now - 10,
        "exp": (now - 120) if expired else (now + 3600),  # 120 s exceeds the 60 s leeway
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
    original_audience = cfg.settings.JWT_AUDIENCE
    cfg.settings.JWKS_URI = ""
    cfg.settings.JWT_SECRET_KEY = SECRET
    cfg.settings.ENVIRONMENT = "testing"
    cfg.settings.JWT_AUDIENCE = AUDIENCE
    yield
    cfg.settings.JWKS_URI = original_jwks_uri
    cfg.settings.JWT_SECRET_KEY = original_secret
    cfg.settings.ENVIRONMENT = original_env
    cfg.settings.JWT_AUDIENCE = original_audience


def test_wrong_audience_raises_jwt_invalid_error():
    token = _make_token(audience="wrong-audience")
    with pytest.raises(JWTInvalidError):
        decode_and_verify(token)


def test_wrong_audience_rejected_on_jwks_path(monkeypatch):
    from src import config as cfg
    import src.utils.jwt_utils as jwt_mod
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    from jose import jwk as jose_jwk

    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    public_jwk = jose_jwk.construct(private_key.public_key(), algorithm="RS256").to_dict()
    public_jwk["kid"] = "test-kid"
    jwks = {"keys": [public_jwk]}

    now = int(time.time())
    token = jwt.encode(
        {"sub": "u1", "aud": "wrong-audience", "iss": ISSUER, "iat": now, "exp": now + 3600},
        private_key,
        algorithm="RS256",
        headers={"kid": "test-kid"},
    )

    cfg.settings.JWKS_URI = "http://keycloak.example/certs"
    cfg.settings.JWT_ISSUER = ISSUER
    monkeypatch.setattr("src.utils.jwt_utils._fetch_jwks", lambda: jwks)

    with pytest.raises(JWTInvalidError):
        decode_and_verify(token)


def test_token_expired_within_leeway_is_accepted():
    now = int(time.time())
    payload = {
        "sub": "user-123",
        "aud": AUDIENCE,
        "iss": ISSUER,
        "iat": now - 100,
        "exp": now - 30,  # expired 30 s ago — within the 60 s leeway
    }
    token = jwt.encode(payload, SECRET, algorithm="HS256")
    claims = decode_and_verify(token)
    assert claims["sub"] == "user-123"


def test_token_expired_beyond_leeway_is_rejected():
    now = int(time.time())
    payload = {
        "sub": "user-123",
        "aud": AUDIENCE,
        "iss": ISSUER,
        "iat": now - 200,
        "exp": now - 90,  # expired 90 s ago — beyond the 60 s leeway
    }
    token = jwt.encode(payload, SECRET, algorithm="HS256")
    with pytest.raises(JWTExpiredError):
        decode_and_verify(token)


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


def test_jwks_cache_ttl_respects_settings(monkeypatch):
    from src import config as cfg
    import src.utils.jwt_utils as jwt_mod

    cfg.settings.JWKS_URI = "http://keycloak.example/certs"
    cfg.settings.JWKS_CACHE_TTL_SECONDS = 42

    monkeypatch.setattr("httpx.get", lambda *a, **kw: MagicMock(
        raise_for_status=MagicMock(), json=MagicMock(return_value={"keys": []})
    ))

    try:
        decode_and_verify(_make_token())
    except Exception:
        pass

    assert jwt_mod._jwks_cache.ttl == 42


def _make_rsa_jwks_and_token(kid="k1", audience=AUDIENCE, issuer=ISSUER):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    from jose import jwk as jose_jwk

    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    public_jwk = jose_jwk.construct(private_key.public_key(), algorithm="RS256").to_dict()
    public_jwk["kid"] = kid
    jwks = {"keys": [public_jwk]}
    now = int(time.time())
    token = jwt.encode(
        {"sub": "u1", "aud": audience, "iss": issuer, "iat": now, "exp": now + 3600},
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )
    return jwks, token


def test_unknown_kid_triggers_cache_invalidate_and_refetch(monkeypatch):
    from src import config as cfg
    import src.utils.jwt_utils as jwt_mod

    cfg.settings.JWKS_URI = "http://keycloak.example/certs"
    cfg.settings.JWT_ISSUER = ISSUER

    stale_jwks = {"keys": []}  # old keys — missing the signing key
    fresh_jwks, token = _make_rsa_jwks_and_token()

    http_call_count = 0
    responses = [stale_jwks, fresh_jwks]

    def fake_get(*args, **kwargs):
        nonlocal http_call_count
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = responses[min(http_call_count, len(responses) - 1)]
        http_call_count += 1
        return resp

    monkeypatch.setattr("httpx.get", fake_get)
    jwt_mod._jwks_cache.clear()

    claims = decode_and_verify(token)
    assert claims["sub"] == "u1"
    assert http_call_count == 2  # fetched stale, failed, invalidated, refetched fresh


def test_unknown_kid_refetch_still_fails_raises_jwt_invalid(monkeypatch):
    from src import config as cfg
    import src.utils.jwt_utils as jwt_mod

    cfg.settings.JWKS_URI = "http://keycloak.example/certs"
    cfg.settings.JWT_ISSUER = ISSUER

    _, token = _make_rsa_jwks_and_token(kid="k1")
    wrong_jwks, _ = _make_rsa_jwks_and_token(kid="k2")  # different key — still won't verify k1-signed token

    http_call_count = 0

    def fake_get(*args, **kwargs):
        nonlocal http_call_count
        http_call_count += 1
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = wrong_jwks
        return resp

    monkeypatch.setattr("httpx.get", fake_get)
    jwt_mod._jwks_cache.clear()

    with pytest.raises(JWTInvalidError):
        decode_and_verify(token)
    assert http_call_count == 2  # fetched, failed, refetched, still failed


def test_stale_jwks_served_when_keycloak_unreachable(monkeypatch, caplog):
    import logging
    from src import config as cfg
    import src.utils.jwt_utils as jwt_mod

    cfg.settings.JWKS_URI = "http://keycloak.example/certs"
    cfg.settings.JWT_ISSUER = ISSUER

    jwks, token = _make_rsa_jwks_and_token()

    # Seed stale cache by doing a successful fetch first
    monkeypatch.setattr("httpx.get", lambda *a, **kw: MagicMock(
        raise_for_status=MagicMock(), json=MagicMock(return_value=jwks)
    ))
    jwt_mod._jwks_cache.clear()
    decode_and_verify(token)  # populates _stale_jwks

    # Now Keycloak goes down — expire the TTL cache so a re-fetch is attempted
    jwt_mod._jwks_cache.clear()
    monkeypatch.setattr("httpx.get", lambda *a, **kw: (_ for _ in ()).throw(httpx.ConnectError("down")))

    with caplog.at_level(logging.WARNING, logger="src.utils.jwt_utils"):
        claims = decode_and_verify(token)

    assert claims["sub"] == "u1"
    assert any("stale" in r.message.lower() for r in caplog.records)


def test_fail_closed_when_cache_cold_and_keycloak_unreachable(monkeypatch):
    from src import config as cfg
    import src.utils.jwt_utils as jwt_mod

    cfg.settings.JWKS_URI = "http://keycloak.example/certs"
    jwt_mod._jwks_cache.clear()
    jwt_mod._stale_jwks = None  # no prior successful fetch

    monkeypatch.setattr("httpx.get", lambda *a, **kw: (_ for _ in ()).throw(httpx.ConnectError("down")))

    with pytest.raises(Exception):  # should not silently succeed
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
    cfg.settings.JWT_ISSUER = ISSUER

    jwks, token = _make_rsa_jwks_and_token()

    call_count = 0

    def fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = jwks
        return resp

    monkeypatch.setattr("httpx.get", fake_get)
    jwt_mod._jwks_cache.clear()

    decode_and_verify(token)  # populates cache
    decode_and_verify(token)  # should use cache — no second http call

    assert call_count == 1, "JWKS endpoint should only be fetched once within TTL window"
