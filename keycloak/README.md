# Local Keycloak dev setup

A profile-gated Keycloak v26 service for developing and smoke-testing the gallery's real auth stack locally. Activate it by adding `--profile keycloak` to your compose command:

```bash
docker compose --profile dev --profile keycloak up
```

Keycloak starts on `http://localhost:8080`. Admin console: `http://localhost:8080/admin` (user `admin`, password `admin`).

The gallery's `app-dev` service waits for Keycloak's `/health/ready` before starting, so the first request never races the JWKS endpoint.

---

## Getting a token

```bash
# Client-credentials token (gallery-test-client service account — all scopes)
python scripts/keycloak_token.py

# Password-grant token for a seeded user
python scripts/keycloak_token.py --grant password --username alice --password dev

# Pipe straight into curl
curl -H "Authorization: Bearer $(python scripts/keycloak_token.py)" \
     http://localhost:8000/api/v1/me
```

Seeded users (password `dev` for all):

| Username | Org | Persona |
|---|---|---|
| `devuser` | gallery-ops | admin |
| `alice` | org-a | contributor |
| `bob` | org-b | contributor |
| `carol` | org-b | contributor |

---

## HS256 vs RS256 — mutual exclusion

The gallery switches auth mode based on whether `JWKS_URI` is set at startup:

- **`JWKS_URI` not set** — HMAC/HS256 path. `scripts/dev_token.py` works; Keycloak tokens are **rejected** (wrong algorithm).
- **`JWKS_URI` set** (i.e. `--profile keycloak` is active) — RS256/JWKS path. `scripts/dev_token.py` tokens are **rejected** (algorithm mismatch). Use `scripts/keycloak_token.py` instead.

The `--profile keycloak` compose override sets `JWKS_URI` automatically in `app-dev`. If you run the gallery binary directly (without compose), set it yourself:

```bash
JWKS_URI=http://localhost:8080/realms/gallery/protocol/openid-connect/certs \
JWT_ISSUER=http://localhost:8080/realms/gallery \
uvicorn src.main:app --reload
```

---

## Editing the realm

**Rule: `keycloak/realm-export.json` is the single source of truth.** Keycloak's storage is ephemeral (H2, wiped on `docker compose down`). Any change you make via the admin UI is lost on next restart unless you re-export and commit the JSON.

Workflow:

1. Make changes in the admin UI at `http://localhost:8080/admin`.
2. Export: **Realm settings → Action → Partial export** (include clients, roles, groups). Save over `keycloak/realm-export.json`.
3. If you changed a client secret, mirror the new value in `.env.example` (and your local `.env`) — see the coupling note below.
4. Restart Keycloak: `docker compose --profile keycloak restart keycloak`.
5. Verify the change survives a cold boot: `docker compose --profile keycloak down && docker compose --profile dev --profile keycloak up`.

---

## Secret coupling — JSON ↔ `.env.example`

Client secrets are hardcoded in `realm-export.json` as sentinel values (e.g. `test-client-secret`, `org-deploy-secret`). The gallery reads these from env vars at startup. **Both sides must match.**

```
realm-export.json clientId          env var                            value
────────────────────────────────────────────────────────────────────────────
gallery-test-client                 KEYCLOAK_ADMIN_CLIENT_SECRET       test-client-secret
org-deploy-example                  (used in smoke tests only)         org-deploy-secret
```

If you rotate a secret in the realm UI and re-export, update `.env.example` (and your `.env`) to match, or `GET /api/v1/me/logout-everywhere` will fail with 401 when the gallery tries to obtain an admin token.

These are **dev-only sentinel values**. Production secrets are managed outside this repo.

---

## Smoke tests

The smoke suite under `tests/smoke/` exercises the full auth stack (visibility, scope gating, API keys, audit attribution) against a live stack. Run after `docker compose --profile dev --profile keycloak up` settles:

```bash
KEYCLOAK_URL=http://localhost:8080 \
GALLERY_API_URL=http://localhost:8000 \
pytest tests/smoke -m smoke -v
```

Smoke tests are excluded from the default `pytest` run (no `KEYCLOAK_URL` set → skipped). CI runs only the unit suite; smoke tests are a pre-merge manual step when touching auth.
