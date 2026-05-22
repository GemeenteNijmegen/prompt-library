#!/usr/bin/env python3
"""Generate a long-lived machine JWT for bootstrap/dev use.

Usage:
    python scripts/generate_key.py --scope prompt:read prompt:create --expires-in-days 365

Reads JWT_SECRET_KEY and JWT_ISSUER from environment or .env file.
"""
import argparse
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Load .env if present
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a machine JWT")
    parser.add_argument(
        "--scope",
        nargs="+",
        required=True,
        metavar="SCOPE",
        help="Space-separated list of permission scopes",
    )
    parser.add_argument(
        "--expires-in-days",
        type=int,
        default=365,
        metavar="DAYS",
        help="Token lifetime in days (default: 365)",
    )
    args = parser.parse_args()

    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        print("ERROR: JWT_SECRET_KEY environment variable is not set", file=sys.stderr)
        sys.exit(1)

    issuer = os.environ.get("JWT_ISSUER", "http://localhost:9000")
    now = int(time.time())
    expires_at = datetime.now(timezone.utc) + timedelta(days=args.expires_in_days)

    try:
        from jose import jwt
    except ImportError:
        print("ERROR: python-jose is required. Run: pip install python-jose[cryptography]", file=sys.stderr)
        sys.exit(1)

    payload = {
        "sub": "machine:cli",
        "scope": args.scope,
        "iss": issuer,
        "iat": now,
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, secret, algorithm="HS256")

    print(token)
    print(f"\nExpires: {expires_at.isoformat()}", file=sys.stderr)
    print(f"Scope:   {' '.join(args.scope)}", file=sys.stderr)


if __name__ == "__main__":
    main()
