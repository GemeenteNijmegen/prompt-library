#!/usr/bin/env python3
"""Guard: no secrets or users may ever land in realm-export.prod.json (ADR 0007).

The production realm export is the checked-in *structural* source of truth only.
Per ADR 0007 §"No secrets or credentials ever committed", zero real or
placeholder credentials belong in it: confidential clients declare no `secret`
(Keycloak generates one on import, retrieved out-of-band), and no users are
seeded (the first Gallery Ops admins are created by hand in the Admin Console
after import). This check exists so a future edit can't quietly reintroduce the
credential-in-JSON pattern that is fine in the dev `realm-export.json`
(`test-client-secret` / `org-deploy-secret`) but would not be fine here.

Scope is deliberately narrow: this only inspects the prod file. The dev
`realm-export.json` is expected to keep its sentinel secrets and seeded users and
is never touched by this guard.

Fails (exit 1) if the prod export contains any of:
  - a `secret` key on any client object,
  - a top-level `users` array with any entries,
  - a `credentials` array (with entries) on any user.

Usage:
  keycloak/check-prod-realm-secrets.py [path-to-realm-export.prod.json]
"""
import json
import sys
from pathlib import Path

DEFAULT_FILE = Path(__file__).resolve().parent / "realm-export.prod.json"


def check(path: Path) -> int:
    try:
        realm = json.loads(path.read_text())
    except FileNotFoundError:
        print(f"\033[31m✗ {path} not found\033[0m", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"\033[31m✗ {path} is not valid JSON: {exc}\033[0m", file=sys.stderr)
        return 1

    violations: list[str] = []

    # 1. No `secret` on any client. Keycloak generates confidential-client
    #    secrets on import; they are retrieved out-of-band, never committed.
    for client in realm.get("clients", []):
        cid = client.get("clientId", "<unknown>")
        if "secret" in client:
            violations.append(f"client '{cid}' has a `secret` key")

    # 2. No seeded users. Gallery Ops admins are created post-import in the
    #    Admin Console; End Users are Entra-federated. Neither belongs here.
    users = realm.get("users", [])
    if users:
        violations.append(f"top-level `users` array has {len(users)} entr" +
                          ("y" if len(users) == 1 else "ies"))

    # 3. No credentials on any user (defense in depth — redundant while (2)
    #    holds, but catches a user smuggled in with baked-in credentials).
    for user in users:
        uname = user.get("username", "<unknown>")
        if user.get("credentials"):
            violations.append(f"user '{uname}' has a `credentials` array")

    if violations:
        print(f"\033[31m✗ {path.name}: credential/user material committed "
              f"(forbidden by ADR 0007)\033[0m", file=sys.stderr)
        for v in violations:
            print(f"\033[31m  - {v}\033[0m", file=sys.stderr)
        print("\nThe production realm export must stay credential-free. See "
              "docs/adr/0007-production-realm-config.md.", file=sys.stderr)
        return 1

    print(f"\033[32m✓ {path.name}: no client secrets, no seeded users, "
          f"no user credentials\033[0m")
    return 0


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FILE
    return check(path)


if __name__ == "__main__":
    sys.exit(main())
