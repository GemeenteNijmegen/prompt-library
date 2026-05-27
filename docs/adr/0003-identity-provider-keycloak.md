# Identity Provider: Keycloak

The Prompt Gallery's identity provider is **Keycloak (v26+)**, deployed with one realm dedicated to the gallery. Each customer Organisation is modelled as a Keycloak *Organization*, federated to that org's existing Entra ID tenant via OIDC identity brokering. Gallery permissions are managed as Keycloak client scopes backed by realm/client roles. End Users authenticate against their Organisation's Entra; the gallery validates Keycloak-issued JWTs via JWKS.

> An earlier draft of this ADR specified Zitadel. That analysis was framed against a single-SPA, first-party gallery. The actual consumer mix — Organisation-deployed chat clients (Copilot Enterprise, custom internal clients) plus API-key fallback for scripts and CI — makes the gallery a multi-client OAuth resource server. Under that reframe, the IdP requirements shift toward first-class OAuth scope ↔ role mapping, mature multi-tenant Organization support, and credible future-readiness for DCR if personal-LLM-account integration becomes a real demand. Keycloak does these better. See ADR 0004 for the access-model decision.

## Context

End Users come from multiple Organisations, each running its own Entra ID tenant. Not every Entra user should have gallery access; access must be explicitly granted. Some Organisations are not in a position to manage app roles or claims inside their own Entra, so permission assignment must be possible entirely within the gallery's IdP, independent of what any given Organisation can configure on their side.

The gallery's JWT contract requires standard OAuth/OIDC claims (`sub`, `iss`, `iat`, `exp`, `aud`, `azp`, `scope`, plus profile claims `name`, `email`, `avatar_url`) and one gallery-specific claim (`org_id`) identifying which Organisation an End User belongs to. The `scope` field carries OAuth scopes that are also the gallery's permission verbs (`prompt:read`, `prompt:write`, `prompt:publish`, `prompt:publish:public`, `prompt:rate`, `prompt:moderate`, `admin:*`).

The authentication flow:

```
End User visits gallery / LLM integration
       ↓
Redirected to Keycloak (login_hint = email)
       ↓
Keycloak matches email domain → Organisation → that org's Entra IdP
       ↓
Entra authenticates the user → returns to Keycloak
       ↓
Keycloak checks: has this user been granted gallery access in this Organisation?
       ├── No  → "Access not provisioned" screen
       └── Yes → issues gallery JWT with assigned scope claims
                         ↓
                  Gallery API validates JWT via JWKS
```

Entra proves identity. Keycloak decides access and permissions.

## Decision

Use **Keycloak (v26+)** as the IdP.

- One Keycloak realm hosts all gallery identity.
- Each Organisation is a Keycloak *Organization*. The Organisation's Entra tenant is configured as the Organisation's external IdP for OIDC identity brokering.
- One Organisation ("Gallery Ops") uses local Keycloak users instead of Entra federation; this is the bootstrap and break-glass account home for Gallery Operators.
- The gallery is modelled as a single Keycloak project/client. Gallery permissions are *client scopes* mapped to realm or client *roles* via role scope mappers. Granting a user a role automatically yields the corresponding scope in their token.
- Org discovery at login uses email-domain mapping (Keycloak verified domains per Organisation). No picker fallback in v1.
- Customer-org provisioning (creating a Keycloak Organization, configuring Entra federation, assigning the first Organisation Admin) is a manual Gallery Operator task. Self-serve org onboarding is out of scope for v1.

Day-to-day per-Organisation user management is delegated: each Organisation has Organisation Admins (a Keycloak role) who self-serve user invitations and gallery-scope assignment for their own org in the Keycloak admin console. Gallery Operators do not gate routine per-user changes.

**Hosting:** TBD. Reuse of a shared Keycloak instance operated by the same platform team is acceptable iff (a) the shared instance is v26+, (b) realm config is self-serve for the gallery team, (c) DCR is permitted in the gallery realm, (d) egress to arbitrary customer Entra tenants is unrestricted, (e) the trust boundary aligns with customer-data expectations, (f) the shared instance's SLA fits. Otherwise run dedicated.

## Why Keycloak over the alternatives

### Keycloak vs Zitadel

Zitadel's clean "organisation with external IdP" model and lightweight Go binary were the original draw. Two things tipped the decision the other way once LLM-client access via the MCP authorization spec became the primary consumer model:

1. **Scope ↔ role mapping is first-class in Keycloak.** Keycloak's *client scope* + *role scope mapper* primitives let you declare `prompt:read` as a client scope, attach it to a role, and have it land in the JWT `scope` claim automatically when the user holds the role. Zitadel emits role grants under a structured URN claim (`urn:zitadel:iam:org:project:roles`) and requires Actions (custom server-side scripts that run at token issuance) to reshape them into a flat `scope` array — extra custom code in the IdP for what should be standard OAuth.
2. **Multi-tenant via identity brokering is the canonical Keycloak pattern**, not a workaround. The earlier framing of "realm-per-org (heavy) or fiddly identity brokering" misread how Keycloak is meant to do this. With v26 Organizations, brokering is bound to org membership cleanly — closing the only remaining structural gap with Zitadel.
3. **DCR future-readiness.** Personal-LLM-account integration is not a v1 use case (see ADR 0004), but it is on the upgrade path. Keycloak has years of production use behind its DCR implementation with client policies, initial access tokens, and per-client scope restrictions. Zitadel's DCR is behind feature flags and is the least proven part of its API surface. If/when the personal-LLM case lands, Keycloak is ready; Zitadel would be a riskier substrate.

Keycloak's operational footprint (Quarkus-based; ~5–15s cold start; ~512MB–1GB steady state; PostgreSQL backend) is heavier than Zitadel's single Go binary but bounded and acceptable. Existing org familiarity with Keycloak is a tiebreaker — when something breaks at 3am, someone has seen Keycloak logs before; nobody has seen Zitadel logs.

### Keycloak vs hand-rolled

A custom FastAPI service would fit the existing stack and emit exactly the JWT contract required. However, building hand-rolled means also building Entra federation, a user provisioning portal, per-user OAuth client/integration management, JWKS + key rotation, DCR with policies, refresh-token rotation and replay detection, consent UX, and full security ownership. That is a substantial project in its own right, and DCR + MCP-spec compliance in particular is not a weekend job. Keycloak gives all of this off-the-shelf.

The hand-rolled path remains viable if the gallery grows into a product that needs full control over auth behaviour, but at current scale the build cost is not justified.

### Keycloak vs hosted IdPs (Auth0, WorkOS, Clerk)

Hosted IdPs solve the same problems with less operational work but park customer-identity data with a third party and add per-MAU cost. The per-Organisation Entra federation pattern works on all of them but customer agreements about data residency and identity-provider sovereignty are more delicate to negotiate. Reconsider if Gallery Ops capacity for IdP operations becomes a real constraint.

## Trade-offs accepted

- **`avatar_url`** is not a standard Keycloak or Entra claim. **v1 resolution: omitted.** The JWT claim is nullable; the gallery frontend renders an initials-in-a-circle fallback (standard web UX). Microsoft Graph fetch via a custom Keycloak authenticator remains the upgrade path if photos become a real requirement — no gallery code changes needed when the claim becomes non-null.
- **Keycloak dependency:** the gallery's JWKS validation points at Keycloak. If Keycloak is unavailable, the gallery cannot authenticate new requests. Acceptable given auth is already a hard dependency.
- **Entra-only federation in v1.** An Organisation that does not run Entra cannot federate. The architecture allows any OIDC-compliant external IdP later — adding Google Workspace, Okta, etc. is a per-Organisation configuration change, not a code change.
- **Entra B2B guests** whose UPN domain differs from their host Organisation's verified domain will not route correctly under email-domain discovery. Documented as a v1 limitation; affected guests must use a UPN matching their host Organisation's domain.
- **Deprovisioning is best-effort within ~7 days for v1.** When a customer removes an End User from Entra, the user's Keycloak refresh chain remains valid until its idle timeout. Manual deprovisioning on request, automated SCIM in a future iteration.

## Upgrade path

JWT validation is behind `src/utils/jwt_utils.py` and the `JWKS_URI` env var. Swapping the IdP means reconfiguring that endpoint and the realm-specific bits (issuer, audience). Scope semantics are intentionally OAuth-standard so the gallery code itself does not change across IdP swaps. The actor model (Organisation, Organisation Admin, End User, Integration — see CONTEXT.md) is IdP-agnostic; how those actors are represented inside the IdP is implementation detail of this ADR.
