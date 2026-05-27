#!/usr/bin/env python3
"""Mint a short-lived HS256 dev token for local curl/testing use.

Refuses to run when ENVIRONMENT=production. Not for production use.

Usage:
    python scripts/dev_token.py [--scope SCOPE ...] [--expires-in-days N]
    JWT_SECRET_KEY=secret python scripts/dev_token.py --scope prompt:read prompt:create
"""
import argparse
import os
import sys
import time

# Ensure project root is on the path when run directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import settings

if settings.ENVIRONMENT == "production":
    print("ERROR: dev_token.py must not be run in production.", file=sys.stderr)
    sys.exit(1)

if not settings.JWT_SECRET_KEY:
    print("ERROR: JWT_SECRET_KEY not set.", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Mint a dev HS256 JWT for local API testing.")
    parser.add_argument("--sub", default="dev-user-001", help="Subject claim (default: dev-user-001)")
    parser.add_argument("--org-id", default="dev-org-001", help="org_id claim")
    parser.add_argument("--azp", default="dev-client", help="azp claim")
    parser.add_argument(
        "--scope",
        nargs="+",
        default=["prompt:read", "prompt:create", "prompt:write", "prompt:publish", "prompt:rate"],
        help="Space-separated list of scopes",
    )
    parser.add_argument("--expires-in-days", type=int, default=1)
    args = parser.parse_args()

    from jose import jwt as jose_jwt

    now = int(time.time())
    payload = {
        "sub": args.sub,
        "org_id": args.org_id,
        "azp": args.azp,
        "scope": args.scope,
        "iss": settings.JWT_ISSUER or "http://localhost:9000",
        "aud": settings.JWT_AUDIENCE,
        "name": "Dev User",
        "email": "dev@localhost",
        "iat": now,
        "exp": now + args.expires_in_days * 86400,
    }
    token = jose_jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")
    print(token)


if __name__ == "__main__":
    main()
