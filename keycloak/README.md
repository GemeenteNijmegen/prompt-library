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

| Username | Org | Persona | Effective permission scopes |
|---|---|---|---|
| `devuser` | gallery-ops | admin | all 13 |
| `dave` | gallery-ops | admin | all 13 |
| `alice` | org-a | contributor | prompt:read + apikey:create + prompt:read:restricted + prompt:create + prompt:write + prompt:rate + prompt:image |
| `bob` | org-b | viewer | prompt:read + apikey:create |
| `carol` | org-b | publisher | all contributor scopes + prompt:publish |

> **Roles in the admin console**: seeded users are assigned the granular permission realm roles directly (e.g. `prompt:create`, `prompt:read`) rather than the composite persona roles (`contributor`, `publisher`). This is what produces role-filtered `scope` claims via the `permission-scopes-from-roles` protocol mapper on `gallery-test-client`. The composite roles exist in the realm for operator use but are not assigned to seeded users.

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

## Two realm files — dev vs prod

There are two realm exports in this directory, and they are **not** interchangeable:

| File | Purpose | Imported by |
|---|---|---|
| `realm-export.json` | Local dev fixture — plaintext client secrets, seeded users (password `dev`), test Organisations (`org-a`/`org-b`), dev-only clients (`gallery-test-client`, `mcp-inspector`, `org-deploy-example`). | `docker compose --profile keycloak` (this dev stack). |
| `realm-export.prod.json` | Production **structural** source of truth — client scopes, realm roles (incl. `organization-admin`), the `gallery-api` and `gallery-app` clients, the `gallery-ops` Organisation shell, the custom **Gallery Ops browser auth flow** (passkey OR password+TOTP, see below), and realm hardening (`sslRequired`, brute-force, password policy, no self-service reset). Contains **zero** client secrets and **zero** users. | The production runbook (imported by a Gallery Operator into the shared Keycloak instance), **never** by the dev stack. |

The dev compose mounts only `realm-export.json` into Keycloak's import directory, so the prod file is ignored locally — `--import-realm` would otherwise try to import two realms both named `gallery`.

Everything the prod realm deliberately leaves out — the first Gallery Ops admin accounts, per-client generated secrets, Entra federation — is provisioned post-import per the runbook, not committed here. (The Gallery Ops passkey/TOTP auth flow itself *is* now committed here as an `authenticationFlows` block — see below.) See [ADR 0007](../docs/adr/0007-production-realm-config.md) for the full rationale.

To smoke-test the prod file against a throwaway instance (matches the dev Keycloak version). The `organization` feature must be enabled or the import fails on the `organization` authenticator in the Gallery Ops flow:

```bash
docker run --rm -p 8081:8080 \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
  -v "$PWD/keycloak/realm-export.prod.json":/opt/keycloak/data/import/realm-export.prod.json:ro \
  quay.io/keycloak/keycloak:26.6.2 start-dev --import-realm --features=organization
```

Before deploying, replace the placeholder `gallery-app` redirect URI / web origin (`https://gallery.example.org`) with the real production SPA origin.

---

## Gallery Ops login: passkey OR password+TOTP

The realm's `browserFlow` is bound to a custom `gallery-ops-browser` flow (ADR 0007, issue #94). Structure:

```
gallery-ops-browser (browserFlow)
├── Cookie                          ALTERNATIVE   — SSO re-entry
├── Identity Provider Redirector    ALTERNATIVE   — honours kc_idp_hint
└── gallery-ops-forms               ALTERNATIVE
    ├── Username Form               REQUIRED      — identity-first (username/email)
    ├── Organization                REQUIRED      — home-realm discovery: if the email
    │                                               domain matches an Entra-federated
    │                                               Organisation, redirect to its IdP and
    │                                               never reach the steps below
    └── gallery-ops-credentials     REQUIRED
        ├── WebAuthn Passwordless    ALTERNATIVE  — passkey, single step
        └── gallery-ops-password-totp ALTERNATIVE
            ├── Password Form        REQUIRED     — governed by realm passwordPolicy
            └── OTP Form             REQUIRED     — TOTP second factor (forces
                                                    CONFIGURE_TOTP if not yet enrolled)
```

The two credential branches are **alternatives, not layers**: a passkey satisfies login on its own (it is already MFA-strength); password+TOTP is the recovery-grade alternative. Federated End Users are peeled off by the `Organization` step before any credential prompt, so the flow only ever exercises passkey/password on **local Gallery Ops** accounts.

### Operational rule: at least 2 Gallery Ops admin accounts, always

`admin`-holding Gallery Ops accounts have no email-based self-service reset (`resetPasswordAllowed: false`, no SMTP) and no lower-level break-glass. **The realm must have ≥2 Gallery Ops admin accounts at all times.** If an operator loses *both* their passkey and their TOTP device, recovery is a **second Gallery Ops admin resetting their credentials via the Admin Console** — there is no other recovery path. Account creation itself is covered by the bootstrap runbook, not here.

---

## Editing the realm

**Rule: `keycloak/realm-export.json` is the single source of truth for local dev.** Keycloak's storage is ephemeral (H2, wiped on `docker compose down`). Any change you make via the admin UI is lost on next restart unless you re-export and commit the JSON. (For production changes, edit `realm-export.prod.json` and re-run the import per the runbook — the dev stack never touches it.)

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
