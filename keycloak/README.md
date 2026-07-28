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

Everything the prod realm deliberately leaves out — the first Gallery Ops admin accounts, per-client generated secrets, Entra federation — is provisioned post-import per the runbook, not committed here. That runbook is **[PRODUCTION.md](PRODUCTION.md)**: import, create ≥2 Gallery Ops admins by hand, enrol their credentials, verify login, and the ≥2-admins / second-admin-recovery operational rules. (The Gallery Ops passkey/TOTP auth flow itself *is* now committed here as an `authenticationFlows` block — see below.) See [ADR 0007](../docs/adr/0007-production-realm-config.md) for the full rationale.

To smoke-test the prod file against a throwaway instance (matches the dev Keycloak version). The `organization` feature must be enabled or the import fails on the `organization` authenticator in the Gallery Ops flow:

```bash
docker run --rm -p 8081:8080 \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
  -v "$PWD/keycloak/realm-export.prod.json":/opt/keycloak/data/import/realm-export.prod.json:ro \
  quay.io/keycloak/keycloak:26.6.2 start-dev --import-realm --features=organization
```

`keycloak/verify-prod-realm.sh` wraps this: it runs structural assertions on the
JSON (no Docker needed — `--offline`), prints the exact `docker run` command
(`--print-docker`), and once the scratch instance is up it asserts the imported
Gallery Ops flow via the admin REST API and provisions a test user for the manual
passkey/TOTP steps. See [Verifying the Gallery Ops flow](#verifying-the-gallery-ops-flow) below.

Before deploying, replace the placeholder `gallery-app` redirect URI / web origin (`https://gallery.example.org`) with the real production SPA origin.

### CI guard: prod realm stays credential-free

`keycloak/check-prod-realm-secrets.py` enforces the "zero secrets, zero users"
rule above so a future edit can't quietly reintroduce the credential-in-JSON
pattern (which is fine in the dev `realm-export.json` but not here). It fails if
`realm-export.prod.json` gains a `secret` key on any client, a non-empty
top-level `users` array, or a `credentials` array on any user. The
`.github/workflows/realm-guard.yml` job runs it on every push/PR that touches
the prod file; it never looks at the dev `realm-export.json`. Run it locally with:

```bash
python3 keycloak/check-prod-realm-secrets.py
```

---

## Integrating a browser SPA (`gallery-app` client)

Any single-page app that logs its own users into the gallery via `gallery-app` (or a client modelled on it) needs two things Keycloak doesn't warn you about up front. Both were worked out the hard way integrating the Leiden AI Challenge platform's Prompt Gallery frontend (`frontend/src/services/keycloakClient.js` / `api.js` in that repo) against a shared, non-local Keycloak instance — recorded here so the next integration doesn't repeat the debugging.

**1. Redirect URIs and Web Origins are two separate fields — set both.**

`keycloak/realm-export.json` (local dev) already has both set correctly for this repo's own dev server:
```json
"redirectUris": ["http://localhost:5173/*", "http://localhost:8000/*"],
"webOrigins": ["http://localhost:5173", "http://localhost:8000"]
```
`redirectUris` governs where Keycloak is willing to send the browser back to after login (an exact/wildcard match on the OAuth `redirect_uri` param — miss it and you get Keycloak's own "Invalid parameter: redirect_uri" error page). `webOrigins` is unrelated and governs CORS on Keycloak's endpoints — specifically the background `fetch` a client-side OAuth library makes to the token endpoint right after the redirect back, to exchange the auth code for tokens. Miss *this* one and the redirect/login itself appears to work, but the token exchange fails silently with a CORS error in the console, the app never becomes authenticated, and (depending on how the SPA reacts to a still-unauthenticated state) you can end up in a login redirect loop that looks unrelated to CORS at all.

`realm-export.prod.json` ships `gallery-app` with placeholder values (`https://gallery.example.org`) in both fields — deliberately, since the prod realm is imported once per environment (per `PRODUCTION.md`) and each environment's Gallery Operator fills in the real origin(s). If you're integrating a new SPA against a **shared, already-imported** Keycloak instance (dev, staging, whatever), you can't do this yourself from the SPA side — ask whoever administers that instance to add your dev origin(s) to *both* fields on the client you're using, not just the redirect URIs.

**2. Keycloak's default CSP blocks iframe-based silent SSO checks, for every client.**

Neither realm export sets a custom `browserSecurityHeaders`, so Keycloak's built-in default applies everywhere this realm is imported: `frame-ancestors 'self'`. That means the common `keycloak-js` pattern of a background session check —
```js
keycloak.init({ onLoad: 'check-sso', silentCheckSsoRedirectUri: `${origin}/silent-check-sso.html` })
```
— will fail in every browser, local dev included: the hidden iframe tries to load Keycloak's auth endpoint from your SPA's origin, and Keycloak's own CSP header refuses to render inside a frame from anywhere but itself. The browser console shows something like:
```
Refused to load '.../protocol/openid-connect/auth?...' because it does not
appear in the frame-ancestors directive of the Content Security Policy.
```
There's no client-side workaround for the CSP itself short of a realm admin adding your origin to `frame-ancestors` (Realm settings → Security defenses → Content-Security-Policy) — not recommended, since it's the anti-clickjacking default for a reason. The simpler fix is to not rely on the iframe at all: drop `silentCheckSsoRedirectUri` (and `onLoad: 'check-sso'` if your app already redirects explicitly when unauthenticated) so session checks fall back to a full top-level redirect instead. That costs a visible redirect flash on first load when there's no session yet, but isn't subject to `frame-ancestors` since it's a real page navigation, not a framed embed. If your app has its own explicit "redirect to login" logic, make sure it's the *only* thing triggering a redirect — running it alongside `onLoad: 'check-sso'`'s own automatic redirect is two independent redirects racing over the same PKCE `state` in `sessionStorage`, which produces a redirect loop distinct from the CSP issue above.

---

## Gallery Ops login: passkey OR password+TOTP

The realm's `browserFlow` is bound to a custom `gallery-ops-browser` flow (ADR 0007, issue #94). Structure:

```
gallery-ops-browser (browserFlow)   — mirrors Keycloak's default browser flow
├── Cookie                          ALTERNATIVE   — SSO re-entry
├── Identity Provider Redirector    ALTERNATIVE   — honours kc_idp_hint
├── gallery-ops-organization        ALTERNATIVE   — home-realm discovery, runs before forms
│   └── (conditional) organization                — if the email domain matches an Entra-
│                                                   federated Organisation, redirect to its
│                                                   IdP; otherwise pass through to forms
└── gallery-ops-forms               ALTERNATIVE
    ├── Username Form               REQUIRED      — identity-first (username/email)
    └── gallery-ops-credentials     REQUIRED
        ├── WebAuthn Passwordless    ALTERNATIVE  — passkey, single step
        └── gallery-ops-password-totp ALTERNATIVE
            ├── Password Form        REQUIRED     — governed by realm passwordPolicy
            └── OTP Form             REQUIRED     — TOTP second factor (forces
                                                    CONFIGURE_TOTP if not yet enrolled)
```

The two credential branches are **alternatives, not layers**: a passkey satisfies login on its own (it is already MFA-strength); password+TOTP is the recovery-grade alternative. The `gallery-ops-organization` subflow is a sibling of `forms` that runs **first** (exactly as Keycloak's built-in `Organization` → `Browser - Conditional Organization` structure): federated End Users are peeled off to their Entra IdP there, so `forms` only ever exercises passkey/password on **local Gallery Ops** accounts. Placing the `organization` authenticator as a bare `REQUIRED` step inside the credential path instead will abort login for local users (they have no IdP to route to) — see #94's history.

### Operational rule: at least 2 Gallery Ops admin accounts, always

`admin`-holding Gallery Ops accounts have no email-based self-service reset (`resetPasswordAllowed: false`, no SMTP) and no lower-level break-glass. **The realm must have ≥2 Gallery Ops admin accounts at all times.** If an operator loses *both* their passkey and their TOTP device, recovery is a **second Gallery Ops admin resetting their credentials via the Admin Console** — there is no other recovery path. Account creation and the step-by-step recovery procedure are covered by the bootstrap runbook, **[PRODUCTION.md](PRODUCTION.md)**, not here.

### Verifying the Gallery Ops flow

`keycloak/verify-prod-realm.sh` automates every check that can be done from the CLI, leaving only the genuinely browser-bound steps (registering a passkey, entering a TOTP code) to a human.

```bash
# Offline — structural assertions on the JSON, no Docker/network. Runs in CI too.
keycloak/verify-prod-realm.sh --offline

# Full run — start the scratch instance (see command above), then:
keycloak/verify-prod-realm.sh
```

The offline layer asserts the flow shape, the `browserFlow` binding, the WebAuthn passwordless policy, and that no flow description exceeds Keycloak's 255-char `DESCRIPTION` column (an import fails hard above that). When a scratch Keycloak is reachable (`KC_URL`, default `http://localhost:8081`) the script additionally logs in as admin, asserts the *imported* flow matches intent via the REST API, provisions the `opstest` test user with the `CONFIGURE_TOTP` + `webauthn-register-passwordless` required actions, and prints the remaining manual browser steps.

**The manual steps (AC 2 & 3 of #94) still need a human**, because WebAuthn enrollment/login can't be driven headlessly without a browser + virtual authenticator:

- **Virtual authenticator (no hardware key needed):** DevTools (F12) → `⋮` → More tools → **WebAuthn** → Enable virtual authenticator environment → Add authenticator with **Supports resident keys** *and* **Supports user verification** both ON (both are required by the realm policy). Keep DevTools open.
- **Enroll (also proves password+TOTP, AC 3):** incognito → `http://localhost:8081/realms/gallery/account`, log in as `opstest`. `CONFIGURE_TOTP` fires (click *"Unable to scan?"* for the secret, then `oathtool --totp -b "<SECRET>"` or any authenticator app); then `webauthn-register-passwordless` fires and the virtual authenticator captures the passkey.
- **Passkey alone (AC 2):** sign out, fresh incognito, log in as `opstest` again — you land in with no password/OTP prompt.
- **Federated routing (AC 4):** add a throwaway organization with a domain + a dummy IdP, then confirm a user whose email matches that domain is redirected at the `Organization` step instead of reaching the passkey/password branches.

---

## Org-deployed client template

`keycloak/templates/org-deployed-client.json` is a **template, not an importable realm fragment** and is not part of `realm-export.prod.json`. It is the copy-paste-and-fill starting point for [ADR 0004](../docs/adr/0004-access-model-oauth-clients.md) step 5 — one confidential OAuth client per chat client a customer Organisation deploys, created via the Admin Console or Admin REST API (`POST /admin/realms/gallery/clients`) at onboarding.

Fill the `{{CLIENT_ID}}`, `{{ORG_SLUG}}`, `{{REDIRECT_URIS}}`, `{{WEB_ORIGINS}}` placeholders, drop the `_comment` key, create the client, then retrieve the Keycloak-generated secret out-of-band (Credentials tab) and hand `client_id` + `client_secret` to the deployment team over a secure channel. No secret is committed.

The template gets the mechanical bits right every time: confidential client, PKCE-S256 required, `gallery-defaults` attached (this is what carries `aud=prompt-gallery-api`, `realm_access.roles`, `sub`, `org_id`), `prompt:read` as the one default gallery scope, and the optional-scope list deliberately **excluding** `admin:*` / `prompt:moderate` / `prompt:publish:public`.

> **Consistency aid, not a security boundary** (ADR 0004 Revision 3): the optional-scope list does *not* gate what lands in a token — effective permissions come from the roles the End User holds (`realm_access.roles`), and no customer End User is ever granted the operator-only roles. Leaving those scopes off the list matches documented intent; it is not technically enforced by the client.

### Verifying the template

`keycloak/verify-org-client-template.sh` mirrors `verify-prod-realm.sh`:

```bash
# Offline — structural assertions on the template JSON, no Docker/network. Runs in CI.
keycloak/verify-org-client-template.sh --offline

# Full run — against a scratch Keycloak (import realm-export.prod.json first, as above):
keycloak/verify-org-client-template.sh
```

The offline layer checks the placeholders, that an instantiated copy is valid JSON, the confidential/PKCE-S256/auth-code shape, the default-vs-optional scope split, and that no forbidden scope is present. When a scratch Keycloak is reachable at `KC_URL` (default `http://localhost:8081`) the live layer instantiates the template, creates the client via REST, asserts the imported config and scope split, retrieves the generated secret, provisions a role-bearing test user, then drives a **full authorization-code + PKCE flow** and decodes the resulting token to confirm `aud=prompt-gallery-api`, `azp=<client>`, and the expected `realm_access.roles` — then cleans up the throwaway client/user. (It briefly swaps the realm `browserFlow` to the built-in `browser` flow so the login can be scripted with curl, and restores it on exit; if the scripted login can't be driven it prints the manual auth-code steps instead.)

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
