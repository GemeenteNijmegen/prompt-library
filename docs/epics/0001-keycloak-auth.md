# Epic: Replace stub auth with Keycloak-backed JWT validation

## Summary

Land the identity and access-control design captured in [ADR 0003 — Identity Provider: Keycloak](../adr/0003-identity-provider-keycloak.md) and [ADR 0004 — Access Model: Org-Deployed OAuth Clients with API-Key Fallback](../adr/0004-access-model-oauth-clients.md). The gallery currently runs against a Phase-2 stub auth dependency; this epic replaces it with real JWT validation against Keycloak, multi-tenant Organisation routing via per-Entra-tenant federation, OAuth-scope-shaped permissions, audit logging, and an API-key fallback path. No customer-facing feature changes — this is foundational work.

See also: [CONTEXT.md](../../CONTEXT.md) for actor-model vocabulary and the visibility/publish model; [PLAN.md](../../PLAN.md) §Identity & Authentication for the per-decision log and §Phase 3 for the implementation phasing.

## Goals

- Real JWT validation against Keycloak via JWKS, with strict `iss` / `aud` / `exp` checks, clock-skew tolerance, and resilient JWKS caching.
- Multi-Organisation support: per-Organisation Entra federation, `org_id` claim threaded through to row-level visibility filtering and audit.
- OAuth-scope-shaped permissions (scopes ↔ Keycloak realm/client roles) replacing the current flat-claim stub.
- API-key fallback for non-OAuth clients (CI, scripts) issued by privileged End Users via the gallery and proxied to Keycloak offline-token issuance.
- Audit log of state-changing actions including the OAuth client (`azp`) that made the call.
- Multi-axis rate limiting (per-IP / `sub` / `azp` / `org_id`).
- Operator-facing logout-everywhere panic button.

## Non-goals (deferred)

- Dynamic Client Registration / personal-LLM-account integration (ADR 0004 §Upgrade path; v2).
- Customer self-serve Organisation onboarding (ADR 0003 §Decision; v2).
- Customer self-serve OAuth-client registration by Organisation Admins (v1.5 if cadence demands).
- SCIM-driven deprovisioning from Entra (v2; v1 accepts ≤7d best-effort posture).
- Audit read API (v1 = direct DB query by Gallery Operators).
- Microsoft Graph–sourced `avatar_url` (v1 = null, frontend renders initials).
- Per-Organisation concurrent-session limits.

## Out-of-repo work (Keycloak side)

These are configuration tasks in the Keycloak realm, not gallery code. Required for production but tracked separately by Gallery Operators — see ADR 0003 §Decision and ADR 0004 §"Organisation onboarding". Briefly:

- Provision the gallery realm on a Keycloak v26+ instance (TBD whether shared or dedicated — see ADR 0003 §Decision).
- Define the gallery as a single Keycloak project/client with `gallery-audience` scope (audience mapper emitting `aud=prompt-gallery-api`), `org_id` protocol mapper, role scope mappers for the permission catalogue.
- Define realm/client roles 1:1 with the scope catalogue in [PLAN.md §Authentication Permissions](../../PLAN.md#authentication-permissions-flat-claims).
- Curate `consentScreenText` per non-OIDC client scope.
- Configure token lifetimes per ADR 0004 §"Token lifetimes" (15-min access, 30d/7d-idle interactive refresh with rotate-on-use + replay detection, 365d offline).
- Restrict `admin:*`, `prompt:publish:public`, `prompt:moderate`, `admin:read_audit` to first-party clients only (not on org-deployed clients' assigned optional scopes).
- Create the "Gallery Ops" Keycloak Organization with local users for bootstrap/break-glass.
- Bootstrap the first customer Organisation following the [ADR 0004 §"Organisation onboarding"](../adr/0004-access-model-oauth-clients.md) runbook (Organization + Entra federation + verified domain + first Org Admin + per-deployment confidential OAuth client).

## In-repo work

### 1. JWT validation core ([ADR 0004 §"JWT contract"](../adr/0004-access-model-oauth-clients.md), [PLAN.md decision 5d, 10c, 13](../../PLAN.md))

`src/utils/jwt_utils.py`:

- Strict `iss` check against `settings.JWT_ISSUER` (no skip-on-empty in production; the prod startup check in `src/config.py` already enforces this).
- Strict `aud` check against `settings.JWT_AUDIENCE` (default `prompt-gallery-api`).
- 60-second `leeway` on `exp` / `nbf` checks.
- JWKS cache TTL configurable via `JWKS_CACHE_TTL_SECONDS` (default 3600).
- On unknown `kid`: invalidate cache, refetch once, retry; fail if still unknown.
- On Keycloak unreachable with cache present: serve stale JWKS, log a warning. On cache absent: fail closed (401).
- Algorithm whitelist enforced (`RS256` for JWKS path, `HS256` for HMAC path) — add an explanatory comment to prevent future regressions.
- Return decoded claims including `sub`, `org_id`, `azp`, `scope`, `name`, `email`, `avatar_url`.

### 2. Auth middleware ([ADR 0004 §"Implications for the gallery code"](../adr/0004-access-model-oauth-clients.md))

`src/middleware/auth.py`:

- Populate `AuthenticatedUser(id, external_id, org_id, name, email, scope, azp, last_seen_at)` from JWT claims.
- Upsert `users` row including `org_id` on every authenticated request.
- Log `azp` on the request boundary (via `RequestIDMiddleware` or here; the value lands in the structured request log).
- Replace the Phase-2 stub dependency wholesale.

### 3. Database migrations (PLAN.md §"Data Model")

New Alembic migration covering:

- Add `org_id TEXT NOT NULL` to `users` (with a backfill/default strategy for any seed/dev data).
- Extend the prompt `status` enum/check from `draft / published / archived` to `draft / published_org / published_public / archived`. Migrate existing `published` rows to `published_org` as the default-safe interpretation (verify with any seed/dev data first).
- Create `prompt_events` table per PLAN.md schema, with the four indexes.

### 4. Row-level visibility ([CONTEXT.md §"Visibility model"](../../CONTEXT.md))

- Add a `visibility_filter(caller)` helper in the prompt query layer.
- Apply uniformly to all read endpoints regardless of scope: `published_public OR (published_org AND org_id = caller.org_id) OR (draft AND (author_id = caller.id OR caller is Org Admin of author's org))`.
- Add `is_org_admin` derivation from `caller.scope` / role claim.

### 5. Scope catalogue update ([PLAN.md §"Authentication Permissions"](../../PLAN.md))

- Update the in-code scope-name constants to match the catalogue: add `prompt:publish:public`, `prompt:moderate`, `apikey:create`, `admin:read_audit`; remove `admin:manage_keys`.
- Update `has_scope` / dependency wrappers accordingly.
- Update status-transition logic to gate `→ published_public` on `prompt:publish:public` and other transitions on `prompt:publish`.

### 6. Audit log writer (PLAN.md §"Data Model" — `prompt_events`)

- Write hooks on every state-changing endpoint (prompt CRUD, status transitions, ratings, API-key issuance/revocation, category/tag CRUD, image upload/delete).
- Schema: `entity_type`, `entity_id`, `action`, `actor_user_id`, `actor_org_id`, `client_id` (= `azp`), `details` (JSON), `created_at`.
- Reads not logged in v1.
- No read API in v1.

### 7. Multi-axis rate limiting ([PLAN.md decision 14](../../PLAN.md))

`src/middleware/rate_limit.py`:

- Add per-`azp` and per-`org_id` buckets alongside the existing per-IP and per-`sub` buckets.
- Reject if any bucket exceeded.
- Defaults from `src/config.py`: `RATE_LIMIT_ANONYMOUS=30`, `RATE_LIMIT_USER=120`, `RATE_LIMIT_CLIENT=600`, `RATE_LIMIT_ORG=1200`.

### 8. Endpoints — `me` and API keys ([PLAN.md §"Authentication & API Keys"](../../PLAN.md), [ADR 0004 §"API-key issuance"](../adr/0004-access-model-oauth-clients.md))

Create `src/routers/me.py` (and remove `src/routers/auth.py` along with `/auth/generate-key`):

- `GET /api/v1/me` — current End User profile (read-only, from JWT).
- `POST /api/v1/me/api-keys` — gated by `apikey:create`; proxies to Keycloak offline-token issuance for the calling End User; returns the token exactly once + persists a metadata row (id, label, created_at, last_used_at, Keycloak session id).
- `GET /api/v1/me/api-keys` — list own keys' metadata.
- `DELETE /api/v1/me/api-keys/{id}` — revoke via Keycloak session/token revocation.
- `POST /api/v1/me/logout-everywhere` — panic button: Keycloak `users/{user-id}/logout` admin call + revoke all own API keys. Confirmation handled SPA-side.

### 9. Delete the gallery's signing path

- Remove `/api/v1/auth/generate-key` from `src/routers/auth.py` and delete the router file.
- Delete `scripts/generate_key.py`.
- Replace with `scripts/dev_token.py` — explicitly dev-only HS256 minting against `JWT_SECRET_KEY`, refusing to run when `ENVIRONMENT=production`. Intended for `curl`-against-local-API.
- Audit: no other code path in the gallery signs tokens after this change.

### 10. Test updates

- `tests/conftest.py`: keep the existing HS256 `make_jwt()` fixture; extend it to populate `org_id`, `azp`, `aud` claims so the new validation accepts the produced tokens.
- Add tests for `aud` rejection, `iss` rejection, clock-skew leeway, unknown-`kid` refetch, stale-cache-serving-on-Keycloak-down.
- Add tests for row-level visibility across all read endpoints (own-org, cross-org, draft author, draft non-author).
- Add tests for the new status transitions including the `prompt:publish:public` gate.
- Add tests for the multi-axis rate-limit buckets, especially per-`azp` and per-`org_id`.
- Add tests for audit-event writing on each state-changing endpoint.
- Add tests for `/me/api-keys` (issuance / list / revoke) — mock the Keycloak admin API calls.
- Add tests for `/me/logout-everywhere` — mock Keycloak admin calls.

### 11. Documentation polish

Already done as part of the design pass; only callout-level changes expected during implementation:

- Any concrete schema discrepancies discovered during migration writing → reflect in PLAN.md §"Data Model".
- Any Keycloak-config quirks discovered during the runbook walkthrough → reflect in ADR 0004 §"Organisation onboarding".

## Suggested sequencing

Tracer-bullet vertical slice first: get one read endpoint (e.g., `GET /api/v1/prompts`) end-to-end with a real Keycloak-shaped JWT (HS256-in-test, RS256-via-JWKS-in-staging), `org_id` enforced via row filter, `azp` logged, audit row written for a write action.

Then expand outward: remaining endpoints, scope catalogue, API-key endpoints, rate-limit multi-axis, logout-everywhere. The order minimises the time spent with a half-replaced auth path.

## Acceptance criteria

- All Phase-2 stub auth call sites are gone; no code path injects a fixed user identity.
- `scripts/generate_key.py` is gone; `scripts/dev_token.py` exists and refuses to run in production.
- `src/config.py` refuses to start when `ENVIRONMENT=production` without `JWKS_URI` + `JWT_ISSUER` or with `JWT_SECRET_KEY` set.
- Tests pass against the new validation path with HS256 fixtures populating the full claim set.
- End-to-end smoke test against a real Keycloak v26+ instance (in CI or staging) demonstrates: federated login from a test Entra tenant, `org_id` claim emitted, row-level visibility working, `prompt:publish:public` blocked for non-Gallery-Operator users, `prompt_events` rows written.
- ADR 0003, ADR 0004, CONTEXT.md, PLAN.md, ARCHITECTURE.md, README.md, `.env.example` all consistent with the implemented state (any drift discovered during implementation reflected back into the docs in the same PR).

## References

- [ADR 0003 — Identity Provider: Keycloak](../adr/0003-identity-provider-keycloak.md)
- [ADR 0004 — Access Model: Org-Deployed OAuth Clients with API-Key Fallback](../adr/0004-access-model-oauth-clients.md)
- [CONTEXT.md](../../CONTEXT.md) — actor model and visibility rules
- [PLAN.md](../../PLAN.md) — decision log (§Identity & Authentication), data model, Phase 3
- [ARCHITECTURE.md](../../ARCHITECTURE.md) — auth flow, layer structure
