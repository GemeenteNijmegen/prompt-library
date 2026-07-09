# Production realm config: hybrid JSON+runbook artifact, shared hosting, role-holding as sole scope enforcement

## Status

accepted

## Context

`keycloak/realm-export.json` is explicitly a local dev fixture (see `keycloak/README.md`) — hardcoded plaintext client secrets, seeded users with the password `dev` (some holding `admin`/`platform-admin`), test Organisations (`org-a`/`org-b`), and dev-only clients (`gallery-test-client`, `mcp-inspector`, `org-deploy-example`). None of that is fit to import into a production realm. Meanwhile ADR 0003 left hosting as `TBD` and the Keycloak-auth epic framed all realm configuration as out-of-repo, Gallery-Operator-driven work with no concrete artifact. This ADR resolves both, and corrects two claims in ADR 0003/0004 that turned out not to match the code.

## Decision

- **Hosting: shared instance** (resolves ADR 0003 §Hosting). All six of ADR 0003's conditions were checked and hold for the specific shared instance in use.
- **Artifact shape: hybrid.** Three new pieces, none of which touch `keycloak/realm-export.json` (dev stays as-is):
  - `keycloak/realm-export.prod.json` — the checked-in structural source of truth: client scopes, realm roles (including `organization-admin`), the `gallery-api` resource-server client, the `gallery-app` first-party SPA, the Gallery Ops Organization, the custom Gallery Ops auth flow. No client secrets, no users, no test Organisations.
  - `keycloak/templates/org-deployed-client.json` — a placeholder-templated client block matching ADR 0004 step 5, copy-pasted and filled in per customer Organisation onboarding. A consistency aid, not a security control (see below).
  - A production runbook covering the steps that can't live in JSON: Entra federation credentials, first Organisation Admin designation, client-secret retrieval, Gallery Ops bootstrap.
- **Scope enforcement is role-holding only**, not client-scope negotiation — see ADR 0004's Revision 3 note. `prompt:*` client-scope optional-lists on clients are cosmetic; the only real control is who is granted `admin:*` / `prompt:moderate` / `prompt:publish:public` (Gallery Operators only, always). This is why the org-deployed client template above is explicitly *not* a security boundary.
- **`organization-admin` is a gallery-code flag only in v1** — see ADR 0003's correction. It does not grant scoped Keycloak admin-console access; per-Organisation user/scope management stays Gallery-Operator-mediated until real fine-grained admin permissions are built (deferred; will need its own ADR, and should confirm GA status on whatever Keycloak version is running before being relied on as a security boundary).
- **No secrets or credentials ever committed:**
  - Confidential clients (`gallery-app`'s eventual confidential siblings, each org-deployed client) declare no `secret` key; Keycloak generates one on import/creation, retrieved by an operator out-of-band.
  - No users are seeded in `realm-export.prod.json`. The first Gallery Ops admin accounts are created by hand in the Admin Console after import (Admin Console access confirmed available, no CLI/kcadm dependency).
- **Gallery Ops authentication: passkey OR password+TOTP**, as alternative branches in a custom browser authentication flow — not layered (passkey is already MFA-strength; the alternative is a recovery path, not a second factor on top of the passkey). Requires a real `authenticationFlows` block in the realm JSON, scoped to the local Gallery Ops login path only (Entra-federated End Users never reach it — home-realm discovery routes them to their Organisation's Entra IdP first).
  - **Operational rule: at least 2 Gallery Ops admin accounts must exist at all times.** Recovery when both a passkey and a TOTP device are lost is a second Gallery Ops admin resetting credentials via the Admin Console — there is no lower-level break-glass than this.
- **No SMTP, `resetPasswordAllowed: false`.** Entra-federated End Users reset via Entra, not Keycloak. Gallery Ops recovery is admin-console-mediated (above), not email-based. No population in the production realm has a legitimate use for Keycloak-native email password reset.
- **`offline_access` dropped entirely** — not granted to any role or client. It was a rev-1 leftover from when API keys were meant to be Keycloak offline tokens; ADR 0004 rev 2 replaced that with opaque gallery-generated secrets specifically because offline tokens don't fit the "long-lived bearer credential for clients that can't do OAuth refresh" need as well (DB-hash-lookup revocation is instant and fine-grained; offline-token revocation is coarser and requires a Keycloak round-trip). Carrying both mechanisms forward would mean two ways to get a long-lived credential, one of them strictly worse.

## Consequences

- `realm-export.prod.json` is meaningfully smaller than the dev export — no test fixtures, no seeded users, no dev-only clients, no offline-token config.
- ADR 0003 and ADR 0004 are corrected in place (revision/correction notes, not superseded) — both had drifted from what the code actually does.
- The org-deployed client template turns ADR 0004 step 5 from pure prose into copy-paste-and-fill, without overstating it as a security control it isn't.
- Fine-grained per-Organisation admin delegation, real fine-grained-admin-permission-based scope narrowing (if ever needed), and SMTP/self-service reset are explicitly deferred, not silently dropped — each would need its own ADR if picked back up.
