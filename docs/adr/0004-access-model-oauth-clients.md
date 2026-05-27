# Access Model: Org-Deployed OAuth Clients with API-Key Fallback

The gallery is an OAuth resource server consumed primarily by **Organisation-deployed chat clients** — Copilot Enterprise tenanted to a specific Organisation, custom internal chat clients built by Organisations, and similar. These clients are configured once per deployment by the Organisation, not by individual End Users. A secondary path covers End-User-owned API keys for scripts, CI pipelines, and any client that cannot do OAuth.

This ADR depends on ADR 0003 (Keycloak as IdP) for the underlying IdP capabilities.

> An earlier draft of this ADR positioned the MCP authorization spec (OAuth 2.1 + Dynamic Client Registration) as the primary access pattern. That framing assumed individual End Users would each connect a personal LLM client to the gallery. The actual consumer mix is dominated by Organisation-deployed chat clients where setup happens once per Organisation by an internal admin — which is not a DCR use case at all. DCR remains on the upgrade path for the day personal-LLM-account integration becomes a real demand.

## Why this shape

- **The setup boundary is the Organisation, not the End User.** When Acme deploys Copilot Enterprise with the gallery wired in, the OAuth client is configured once by Acme's IT/admin team. All Acme End Users consume that one client via their existing chat-client login. The "End User pastes a registration URL into their chat client" UX does not fit this model — there is nothing to paste because there is no per-user setup.
- **Manual client registration is fine at this cadence.** Organisations onboard at a low rate (one-time event per customer). Gallery Operators registering one Keycloak client per Organisation-deployment is bounded work. Self-serve client registration by Organisation Admins is plausible later but not required for v1.
- **The Entra-tenant allowlist is the access gate.** Whoever can authenticate is determined by which Entra tenants are federated as IdPs on Keycloak Organisations. A user from a non-federated tenant cannot get past the login screen. This is the strong allowlist; nothing else needs to gate "who can use the gallery."
- **API keys cover the long tail.** Scripts, CI pipelines, OpenWebUI without OAuth, ad-hoc tooling — End Users self-serve their own long-lived offline tokens (Keycloak's `offline_access` scope). Revocable via the gallery UI or Keycloak admin.

## Client model

| Client kind | Registration | Credentials | OAuth flow |
|---|---|---|---|
| **Org-deployed chat client** | Manually registered in Keycloak by Gallery Operator at Organisation onboarding (one per deployment) | Confidential — `client_id` + `client_secret`, baked into the deployment's secret store | Authorization-code + PKCE |
| **Gallery first-party SPA** | Manually registered in Keycloak by Gallery Operator (one client, lives in the gallery realm config) | Public — PKCE-only | Authorization-code + PKCE |
| **API key (Keycloak offline token)** | Issued via `POST /api/v1/me/api-keys` (gallery proxies to Keycloak) | Long-lived JWT, presented as `Authorization: Bearer ...` | n/a — token already issued |

No clients are dynamically registered in v1. Self-serve registration (DCR) is in the upgrade path.

## JWT contract

Tokens issued by Keycloak carry:

| Claim | Value | Source |
|---|---|---|
| `iss` | Keycloak realm URL | Keycloak |
| `sub` | Keycloak user UUID | Keycloak |
| `aud` | `"prompt-gallery-api"` (required); MAY also include `client_id` | Audience mapper on the gallery client scope |
| `azp` | The requesting client's `client_id` (the org-deployed client, the SPA, or the API-key client) | Keycloak default |
| `iat`, `exp` | Standard | Keycloak |
| `scope` | Space-delimited list of OAuth scopes granted (intersection of requested ∧ user's roles) | Keycloak role scope mappers |
| `org_id` | Keycloak Organization ID of the End User's Organisation | Protocol mapper on the gallery client scope |
| `name`, `email` | From the End User's profile (federated from Entra) | OIDC standard claims |
| `avatar_url` | Nullable. Omitted in v1; frontend renders initials fallback. See ADR 0003 for the upgrade path. | — |

The gallery validates `iss` (must equal the configured Keycloak realm URL), `aud` (must contain `"prompt-gallery-api"` exactly), `exp`, and the signature (via JWKS). It does **not** validate `azp` for authorization but **does log it** on every authenticated request for audit and traceability.

## Scope catalogue

Scopes correspond 1:1 to gallery permission verbs. Each scope is a Keycloak client scope with a role scope mapper attached; the scope appears in a user's token iff they hold the corresponding role.

| Scope | Grants | Default? | Available to org-deployed clients? |
|---|---|---|---|
| `openid`, `profile`, `email` | OIDC baseline | Default | Yes |
| `prompt:read` | Read prompts subject to row-level visibility filter | **Default** for all authenticated End Users | Yes |
| `prompt:write` | Create/edit own drafts | Optional | Yes |
| `prompt:publish` | Promote a prompt to `published_org` within own Organisation | Optional | Yes |
| `prompt:publish:public` | Promote a prompt to `published_public` (visible across Organisations) | Optional | **No** — Gallery Operators only (first-party SPA / admin tooling) |
| `prompt:rate` | Submit/view own ratings | Optional | Yes |
| `prompt:moderate` | Cross-organisation moderation | Optional | **No** — Gallery Operators only |
| `admin:*` | Realm-wide admin actions | Optional | **No** — first-party clients only |

`prompt:read` is the only non-OIDC scope that is *default* — being an authenticated End User implies "may read what they're allowed to see." All other gallery scopes are optional and must be explicitly requested by the client, with consent text curated per scope in Keycloak.

`admin:*`, `prompt:publish:public`, and `prompt:moderate` are restricted at the Keycloak client-scope level — only first-party clients have these in their optional-scope list. An org-deployed client cannot request them.

Row-level visibility (`public OR own-org OR own-draft-or-org-admin`) is enforced by the gallery regardless of scope; scopes gate verbs, not row access. The `org_id` claim is what powers the row filter.

## Token lifetimes

| Token | Absolute TTL | Idle | Rotation | Used by |
|---|---|---|---|---|
| Access token (JWT) | 15 minutes | n/a | n/a | All clients on every API call |
| Refresh token (interactive) | 30 days | 7 days | Rotate-on-use, replay detection | Org-deployed clients, first-party SPA |
| API key (offline token) | 365 days | None | None | API-key fallback path |

Replay detection on interactive refresh tokens means Keycloak revokes the entire refresh chain if a previously-used refresh token is presented again (OAuth 2.1 BCP). This is the headline defence against refresh-token leakage.

**Deprovisioning posture (v1):** when an Organisation removes an End User from their Entra tenant, the user's Keycloak refresh chain continues to work until its idle timeout (up to 7 days). Best-effort, with manual deprovisioning on request. SCIM-driven sync from Entra → Keycloak is a v2 path.

## Audience policy

Tokens carry `aud = ["prompt-gallery-api", <client_id>]` (or `aud = "prompt-gallery-api"` alone with `client_id` in `azp`). The gallery enforces `"prompt-gallery-api"` in `aud` strictly. This means:

- A token whose audience does not include `"prompt-gallery-api"` is rejected — including tokens issued for some other resource server in the same Keycloak realm.
- A client must request the gallery's resource (via the `gallery-audience` client scope, configured on each client) to obtain a token the gallery will accept.
- `azp` (the OAuth "authorized party" claim) identifies *which* client made any given request. Gallery logs include `azp` so operational forensics can answer "which org-deployed client made this call" or "which API key is responsible for this load spike."

## Organisation onboarding

Per-Organisation onboarding is a Gallery-Operator-driven, multi-step ops task:

1. Create a Keycloak Organization for the customer.
2. Configure their Entra tenant as the Organization's external IdP (paste tenant ID + client ID + client secret obtained from the Organisation's Entra app registration).
3. Verify the Organisation's email domain(s) on the Keycloak Organization (drives email-domain login routing — see ADR 0003).
4. Designate the first Organisation Admin (assign the `organization-admin` role).
5. For each chat client the Organisation will deploy: create a confidential OAuth client in Keycloak with the gallery-audience scope, the appropriate scopes from the catalogue, the deployment's redirect URIs, and PKCE required. Hand the `client_id` + `client_secret` to the Organisation's deployment team via a secure channel.

Self-serve Organisation onboarding is out of scope for v1. Self-serve client registration by Organisation Admins (creating their own confidential clients inside their own Organisation in Keycloak) is plausible as a v1.5 increment if the cadence picks up — the Keycloak permissions exist.

## API-key issuance (fallback path)

API keys are not a normal End-User concern. They are issued in two distinct shapes:

- **Personal API keys for privileged End Users** (Organisation Admins, designated developers): created via `POST /api/v1/me/api-keys`, gated by the `apikey:create` scope which Organisation Admins assign sparingly. The key is issued as an offline token in the calling End User's name; usage appears as that user in audit logs (with `azp` distinguishing it from interactive sessions).
- **Service-identity keys for headless users** (CI pipelines, automation, OpenWebUI service accounts): the Organisation Admin creates a local Keycloak user inside their Organisation (not Entra-federated), grants the user appropriate scopes, and issues an offline token for that user — all in Keycloak admin, not via the gallery API. The headless user persists independently of any human Org Admin's lifecycle, which is the point.

The gallery's `POST /api/v1/me/api-keys` flow (personal keys):

1. Ask Keycloak for an offline token (`scope=offline_access ...`) for the calling End User against the dedicated API-key client.
2. Return the resulting JWT to the End User exactly once.
3. Record the token's Keycloak session ID and a user-supplied label in the gallery DB so the user can list and revoke their own API keys.

The gallery itself does not sign tokens. The legacy `/api/v1/auth/generate-key` endpoint that signed HS256 JWTs with a local secret is removed; the dev-mode HMAC fallback in `src/utils/jwt_utils.py` is retained for tests and local development without Keycloak running, but is hard-blocked in production via `ENVIRONMENT=production`.

## Implications for the gallery code

Concrete changes against the current code:

- `src/utils/jwt_utils.py`: add audience check (`audience="prompt-gallery-api"`), surface `azp` in the decoded claim set, surface `org_id`.
- `src/middleware/auth.py`: pass `azp` and `org_id` into `AuthenticatedUser`; log `azp` on every request.
- `src/routers/auth.py`: remove local HS256 signing for `/auth/generate-key`. Dev-mode HMAC for tests only.
- New endpoints under `src/routers/me.py` (or similar): `POST /api/v1/me/api-keys` (issue offline token), `GET /api/v1/me/api-keys` (list), `DELETE /api/v1/me/api-keys/{id}` (revoke).
- Row-level visibility filter helper added to the prompt query layer; applied uniformly on every read endpoint regardless of scope.
- PLAN.md scope/permission catalogue and JWT contract updated to match this ADR.

## Trade-offs accepted

- **Manual client registration per Organisation deployment.** Doesn't scale to thousands of Organisations, but the actual cadence makes it fine for v1 and the obvious near-term future. Self-serve registration (by Organisation Admins, or by DCR) is a clear v1.5/v2 evolution.
- **No personal-LLM-account path in v1.** An individual developer wanting to wire personal Claude.ai to the gallery has to use an API key (and accept that their personal Claude does not understand OAuth-with-the-gallery). DCR is the future answer; if the demand becomes real, enable Keycloak's DCR with strict client policies and a per-Organisation opt-in.
- **One client per deployment, not one per Organisation.** If Acme deploys both Copilot Enterprise and a custom internal client, that's two Keycloak clients, two `client_secret` artifacts. Marginal overhead, correct security shape.

## Upgrade path

When the personal-LLM-account case becomes a real demand (v2-ish):

- Enable Keycloak's Dynamic Client Registration with strict client policies (PKCE-S256 mandatory, redirect URI required, allowed-scope allowlist excluding `admin:*` / `prompt:publish:public` / `prompt:moderate`, refresh-TTL caps, rate limits on the DCR endpoint, auto-cleanup of dormant clients).
- Add per-Organisation policy to opt in/out of DCR — high-security customers can keep manual-only.
- Optionally add a gallery-side endpoint to issue initial access tokens if any customer demands gated DCR.
- Add `/api/v1/me/integrations` to list DCR-registered clients alongside API keys.

The MCP-spec discovery surface (`.well-known/oauth-authorization-server`, `.well-known/openid-configuration`) is provided by Keycloak directly out of the box, so adding DCR later is largely a Keycloak-config + policy-design exercise, not a gallery code change.
