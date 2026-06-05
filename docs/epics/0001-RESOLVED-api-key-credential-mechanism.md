# RESOLVED DESIGN QUESTION: How does `POST /me/api-keys` issue a credential?

**Status:** ✅ **RESOLVED 2026-06-05 — Option B (opaque DB-backed API keys).**
**Raised:** 2026-06-03, during PR #59 (API-key lifecycle + logout-everywhere smoke tests).
**Epic:** [0001 — Keycloak auth](./0001-keycloak-auth.md). **ADR:** [0004 rev 2](../adr/0004-access-model-oauth-clients.md). **PLAN:** decisions 1b, 11a, 11c, 11d.
**Branch where this surfaced:** `feat/issue-51-api-key-smoke-tests` (HEAD `a1001f7`).

---

## RESOLUTION (2026-06-05)

**Decision: Option B — opaque, gallery-issued API keys.** `POST /me/api-keys` does
**not** mint a Keycloak token. The gallery generates a random secret `pg_<random>`,
stores only its SHA-256 hash + a scopes snapshot + a 365-day `expires_at`, and returns
the raw secret exactly once. Requests presenting a key are resolved by DB hash lookup to
the same `AuthenticatedUser` that the JWT path produces — one authorization path, two
credential front doors. Revocation is a DB update; `azp` is logged as `apikey:<id>`.

**Sub-questions, as decided:**
1. **A vs B vs hybrid → B.** V2 cannot mint offline tokens; V1 is deprecated and being
   removed, so Option A is a time bomb for *foundational* auth. B is durable
   (Keycloak-version-independent), fully unit-testable, and matches the paste-a-key UX
   that MCP servers and chat clients expect (GitHub-PAT / Stripe model).
2. **Scope resolution → snapshot all the issuer's scopes at issuance** (stored on the key
   row). org_id is read live from the owning user row (identity, not capability).
   Staleness on role-reduction is handled by revocation, consistent with the documented
   ≤7-day best-effort deprovisioning posture.
3. **Schema → drop `keycloak_session_id`; add `token_hash` (unique), `token_prefix`,
   `scopes`, `expires_at`.** Migration `d5e6f7a8b9c0`.
4. **Mocked-only regression risk → fixed.** Added `tests/test_api_key_auth.py`, a
   non-mocked path (issue → present key → authenticate; revoked/expired rejected) so a
   mechanism failure can no longer hide behind a mocked Keycloak boundary.

**Why this is compatible with the primary (per-user) flow.** The "admin installs the MCP
server once, each user acts as themselves via Keycloak" flow is the *OAuth* path
(authorization-code + PKCE, per user) — it does not use API keys at all and is unchanged.
Opaque keys are only the fallback for headless/individual self-serve use. An API key is
one bearer credential = one identity by definition, so per-user identity is necessarily
the OAuth path; the two are complementary.

**Implemented in:** `src/services/api_key_service.py`, `src/middleware/auth.py`
(`_authenticate_api_key`), `src/routers/me.py`, `src/models/api_key.py`,
`src/schemas/api_key.py`, migration `d5e6f7a8b9c0`, `src/services/keycloak_client.py`
(offline-token issuance + per-key session revocation removed; interactive-session logout
kept). Tests: `tests/test_me_api_keys.py`, `tests/test_api_key_auth.py`,
`tests/test_logout_everywhere.py`, `tests/smoke/test_api_key_lifecycle.py`. Docs: ADR 0004
rev 2, PLAN 1b/11a/11c/11d, this epic §8/§10.

The analysis below is retained as the historical record of how the decision was reached.

---

## TL;DR

The API-key feature is built on the assumption that the gallery can ask Keycloak to
mint a **365-day offline token** for the calling End User, given only that user's
access token. The chosen mechanism — **Keycloak Standard Token Exchange (V2)** —
**cannot produce offline tokens by design.** The only Keycloak mechanism that can
(legacy V1 token exchange) is a **deprecated preview feature slated for removal.**

We need to decide between keeping the offline-token design on a doomed mechanism (A)
or redesigning API keys as opaque DB-backed credentials (B). Until then, the #59 smoke
tests cannot pass.

---

## What the feature is supposed to do

ADR 0004 §"API-key issuance" and PLAN 11a/11c:

- `POST /api/v1/me/api-keys`, gated by `apikey:create`.
- Step 1 (ADR, mechanism-agnostic): *"Ask Keycloak for an offline token (`scope=offline_access`) for the calling End User against the dedicated API-key client."*
- Return the offline JWT exactly once; store `{id, label, created_at, keycloak_session_id}`.
- Revoke via Keycloak session deletion (`DELETE /admin/realms/{realm}/sessions/{id}`).
- `logout-everywhere` deletes all user sessions + revokes all key sessions.

PLAN commitments this rests on:
- **1b / 11a:** "Keycloak offline tokens (365 d) for API-key fallback." "Gallery does **not** sign tokens."
- "Single issuer; one validation path." (API-key requests carry the same JWT shape — `org_id`, `scope`, `azp` — and flow through the same JWKS validation as interactive tokens.)

## Current implementation (the part that doesn't work)

`src/services/keycloak_client.py::issue_offline_token` does an RFC 8693 token exchange:

```
grant_type      = urn:ietf:params:oauth:grant-type:token-exchange
client_id       = gallery-apikey-issuer
subject_token   = <caller's access token>
requested_token_type = ...:access_token      # changed from refresh_token in a1001f7
scope           = offline_access
```

…and reads the offline token from `response["refresh_token"]`.

## Root cause (definitive, sourced)

An offline token requires an **offline user session**.

1. **Standard Token Exchange V2 never creates a new user session**
   ([keycloak#37832](https://github.com/keycloak/keycloak/issues/37832)). Its only
   refresh-token mode is the client switch
   `standard.token.exchange.enableRefreshRequestedTokenType`, whose values are `NO`
   (default) and `SAME_SESSION`. `SAME_SESSION` reuses the subject token's (online)
   session and the docs state it **"will not be allowed to request an offline token
   (using `scope=offline_access`)."**
   → **No V2 configuration can return an offline token.**
   Observed: the exchange returns `200` with `refresh_expires_in` but **no
   `refresh_token`** field.
   Source: <https://www.keycloak.org/securing-apps/token-exchange>
2. **Legacy V1 token exchange CAN** mint offline tokens (one of its four use-cases),
   but it is a **deprecated preview feature** that "may not be backwards compatible
   with future Keycloak versions and **will be finally removed.**"
   Sources: <https://www.keycloak.org/securing-apps/token-exchange>,
   <https://www.keycloak.org/docs/latest/upgrading/index.html>
3. V1 and V2 can be enabled together (V2 for internal-internal, V1 for the offline
   use-case).

This also matters **functionally**, not just technically: an API key must outlive the
user's interactive SSO session — that's the whole point. A `SAME_SESSION` online
refresh token dies when the browser session ends, which makes it useless as an API key.
So "offline" is a hard requirement, not incidental.

## Why this surfaced so late

The unit tests for #36/#37 (`tests/test_me_api_keys.py`,
`tests/test_logout_everywhere.py`) **mock the Keycloak client**, so they pass
regardless. PR #59's smoke tests are the first execution against a live Keycloak.
**Process note:** a mocked-only integration boundary hid a design-level failure through
two "closed" issues.

## Fixes already applied while chasing this (all real, none sufficient)

The error advanced through several layers — each fix was necessary but revealed the next
wall. These changes are currently in the working tree on
`feat/issue-51-api-key-smoke-tests` (NOT yet committed) and are valid regardless of which
option we pick, **except** the ones marked V2-specific:

1. `docker-compose.yml`: `KC_HOSTNAME: http://localhost:8080` on the Keycloak service.
   Fixes `400 "Invalid token"` — start-dev derived its issuer from the request host, so
   tokens minted at `localhost:8080` were rejected when the app exchanged them via the
   compose-internal `keycloak:8080`. **Keep regardless** (correct hostname pinning).
2. `keycloak/realm-export.json`: audience mapper on the `apikey:create` client scope
   adding `gallery-apikey-issuer` to `aud`. Fixed `403 "Client is not within the token
   audience"`. **V2-specific** — only needed for the exchange approach.
3. `keycloak/realm-export.json`: `standard.token.exchange.enabled` on
   `gallery-apikey-issuer` (commit `06146e6`) + `offline_access` in its optional scopes.
   **V2-specific.**
4. `keycloak/realm-export.json`: `service-account-gallery-test-client` user granted
   `realm-management` roles `manage-users`, `view-users` — needed for the revoke /
   logout-everywhere admin API calls (`DELETE .../sessions/...`). **Keep regardless** —
   both options still revoke via the admin API for the session path, and it's needed for
   logout-everywhere's interactive-session termination either way.
5. `src/services/keycloak_client.py`: graceful `KeycloakError` when the exchange returns
   no `refresh_token` (self-diagnosing instead of a bare `KeyError`). **Keep** (defensive).

`config.py` `KEYCLOAK_REALM` default was briefly changed to `gallery` then reverted to
`prompt-gallery` (the dev compose sets `KEYCLOAK_REALM=gallery` explicitly, so the
default is irrelevant to the stack).

## Options

### A — Legacy V1 token exchange
- **Pros:** Keeps ADR/PLAN intent exactly (real Keycloak offline token, one issuer,
  gallery signs nothing, same validation path). #59 smoke tests pass ~as written.
- **Cons:** Built on a **deprecated feature being removed** — a future Keycloak upgrade
  will break it. Requires `--features=token-exchange` (have it) **plus**
  `admin-fine-grained-authz` and token-exchange permission policies in the realm export.
  Requires reverting `requested_token_type` back to `refresh_token` and NOT setting
  `standard.token.exchange.enabled` (which forces V2). Cannot be verified without a live
  Keycloak.

### B — Opaque DB-backed API keys
- **Pros:** No Keycloak offline token at all — gallery generates a random secret, stores
  a hash, validates by DB lookup. Industry standard (GitHub PAT / Stripe). Keycloak-
  version-independent. **Fully unit-testable without Docker.** Revocation is a DB update.
  Still compatible with "gallery owns no signing key" (opaque string ≠ signed JWT).
- **Cons:** Breaks PLAN 1b "single validation path" — adds a second auth path alongside
  JWT. Must resolve an API-key request to a user + scopes + org_id (see open sub-question
  below). **Rewrites #59's smoke tests** (steps 2 & 5 exchange the token at Keycloak and
  assert Keycloak rejects it post-revoke — meaningless for opaque keys; replace with
  "call the gallery API with the key, then assert 401 after revoke"). Edits ADR 0004 /
  PLAN 1b/11a/11c.

### C — (ruled out) Some other non-deprecated Keycloak way to mint an offline token
Investigated and rejected: offline tokens require interactive user consent (auth-code /
ROPC with `offline_access`) or exchange/impersonation. The backend holds only the access
token. V2 impersonation+offline is a *future* enhancement, not shippable now. Pulling an
offline token from the SPA at login (SPA requests `offline_access`, forwards it) is
architecturally messy and puts offline tokens in the browser — not pursued.

## Recommendation (for discussion, not decided)

Research tilts toward **B** for durability: V2 is the supported future, V1 is on death
row, so new code on V1 is a time bomb. If #59-green-now matters more than durability,
**A with a tracked migration issue** is a defensible explicit stopgap.

## Open sub-questions to resolve before implementing

1. **A (stopgap) vs B (durable redesign) vs hybrid** (ship A now, file migration issue)?
2. **If B:** how does an API-key request resolve `scope` / `org_id`?
   - **Snapshot at issuance** (store scopes+org_id on the key row): fast, no Keycloak
     dependency per request, but goes stale if the user's roles/org change. Revocation =
     mark row revoked.
   - **Live lookup per request** (resolve from the user row / Keycloak): always current,
     but reintroduces a per-request dependency and latency. 
   - This choice drives revocation + staleness semantics and how `logout-everywhere`
     interacts with keys.
3. **If B:** does `keycloak_session_id` on the `api_keys` row still make sense, or does
   the schema change (drop session id, add `token_hash`, `last_used_at`)? Migration impact.
4. **Either way:** should the mocked-only unit tests for #36/#37 be supplemented with a
   non-mocked path so a design regression like this can't hide behind mocks again?

## Key references

- ADR 0004 §"API-key issuance", §"Logout-everywhere" — `docs/adr/0004-access-model-oauth-clients.md`
- Epic 0001 §8 (endpoints), §"Out-of-repo work" (token lifetimes: 365d offline) — `docs/epics/0001-keycloak-auth.md`
- PLAN.md decisions 1b, 11a, 11c, 11d; §"Authentication & API Keys"
- Keycloak token exchange: <https://www.keycloak.org/securing-apps/token-exchange>
- STE V2 GA announcement: <https://www.keycloak.org/2025/05/standard-token-exchange-kc-26-2>
- "Token Exchange v2 features of v1": <https://github.com/keycloak/keycloak/issues/39686>
- "Avoid creating user sessions from the token exchange": <https://github.com/keycloak/keycloak/issues/37832>
- Implementation: `src/services/keycloak_client.py`, `src/routers/me.py`
