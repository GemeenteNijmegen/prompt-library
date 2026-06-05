"""Opaque API-key generation and hashing (ADR 0004 §"API-key issuance").

API keys are gallery-issued random secrets, not Keycloak tokens. The gallery
generates a high-entropy secret, hands it to the user exactly once, and stores
only its SHA-256 hash. Validation is a constant-time DB lookup by hash.

SHA-256 (not bcrypt/argon2) is deliberate: the secret carries ~256 bits of
entropy, so an offline brute-force of the hash is infeasible. Slow password
hashing only buys protection for *low*-entropy human-chosen secrets, which these
are not — and it would add latency to every authenticated request.
"""
import hashlib
import secrets

# User-visible prefix so a leaked key is recognisable in logs/scanners and the
# UI can label it (mirrors `ghp_`, `sk-`, etc.).
KEY_PREFIX = "pg_"

# How much of the raw key to retain for display in GET /me/api-keys. Enough to
# disambiguate keys, far too little to be useful to an attacker.
PREFIX_DISPLAY_LEN = len(KEY_PREFIX) + 8

# Absolute lifetime of an issued key, matching the previous offline-token TTL
# (ADR 0004 §"Token lifetimes").
DEFAULT_TTL_DAYS = 365


def generate_api_key() -> tuple[str, str, str]:
    """Mint a new key.

    Returns ``(raw_token, token_hash, token_prefix)``. Only the hash and the
    prefix are persisted; ``raw_token`` is returned to the caller once and then
    discarded.
    """
    raw_token = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return raw_token, hash_token(raw_token), raw_token[:PREFIX_DISPLAY_LEN]


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def is_api_key(token: str) -> bool:
    """True if a bearer credential is an opaque gallery key rather than a JWT."""
    return token.startswith(KEY_PREFIX)
