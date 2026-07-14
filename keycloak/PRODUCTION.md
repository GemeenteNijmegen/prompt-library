# Production Keycloak runbook — Gallery Ops bootstrap

This is the doc a Gallery Operator reaches for when standing up (or recovering)
the production `gallery` realm on the shared Keycloak instance. It covers the
steps that deliberately **cannot** live in `realm-export.prod.json`: importing
the realm, creating the first Gallery Ops admin accounts by hand, enrolling their
credentials, and verifying login.

You should be able to follow this without reading the ADRs. The rationale lives
in [ADR 0007](../docs/adr/0007-production-realm-config.md); the *procedure* lives
here. Where a term needs defining (Gallery Operator, Organisation, the `admin`
role), this doc defines it inline.

> **This is a Human-in-the-Loop procedure.** Creating real accounts against the
> shared production instance and physically enrolling a passkey/TOTP credential
> cannot be automated — no CLI, kcadm, or agent path is used or assumed. Every
> step below is performed by a human in the Keycloak Admin Console and a browser.

---

## 0. Before you start

**You need:**

- **Admin Console access** to the shared production Keycloak instance (the master-realm
  admin, or an account with realm-management rights over the `gallery` realm).
  No `kcadm`/CLI access is required or assumed.
- The `keycloak/realm-export.prod.json` file from this repo, at the revision you
  intend to deploy.
- The **real production SPA origin** for the gallery front-end (to replace the
  `https://gallery.example.org` placeholder — see step 1.3).
- A **second person** available to be the second Gallery Ops admin. The realm has
  no email-based self-service reset and no lower-level break-glass, so a single
  admin is a lockout waiting to happen. See [§5](#5-operational-rules-and-recovery).

**Terms used below:**

| Term | Meaning here |
|---|---|
| **Gallery Operator** / **Gallery Ops admin** | Staff who run the gallery service and its Keycloak realm. A **local** Keycloak account (no Entra federation) that is a member of the **Gallery Ops** Organisation and holds the `admin` realm role. |
| **`admin` realm role** | The composite role that carries every operator scope — it composites `publisher` + `prompt:publish:public` + `prompt:moderate` + `admin:manage_taxonomy` + `admin:manage_users` + `admin:read_audit`. Assigning `admin` is all a Gallery Ops account needs. |
| **`organization-admin` realm role** | A **gallery-facing flag only** in v1 (draft visibility beyond one's own Org). It does **not** grant scoped Keycloak admin-console access. Gallery Ops staff do **not** need it — it's for federated Organisation Admins. Assign it only if a specific account also acts as an Organisation Admin (rare for Ops staff). |

---

## 1. Import the realm

`realm-export.prod.json` is the **structural** source of truth: client scopes,
realm roles, the `gallery-api` (bearer-only resource server) and `gallery-app`
(public SPA) clients, the `gallery-ops` Organisation shell, the custom Gallery Ops
browser auth flow, and realm hardening (`sslRequired`, brute-force, the 12-char
password policy, no self-service reset). It contains **zero** client secrets and
**zero** users by design — those are provisioned here, post-import.

1.1 **Confirm the `organization` feature is enabled** on the production instance.
The Gallery Ops auth flow uses the `organization` authenticator; import fails
without it. (On a self-managed server this is `--features=organization` or the
equivalent in your deployment config. On a managed instance, confirm with whoever
operates it.)

1.2 **Import.** Admin Console → realm dropdown (top-left) → **Create realm** →
**Resource file: Browse** → select `realm-export.prod.json` → **Create**. If a
`gallery` realm already exists you are recovering, not bootstrapping — do not
re-import over a live realm; skip to the step you need.

1.3 **Set the real SPA origin.** The committed `gallery-app` client ships a
placeholder redirect URI / web origin (`https://gallery.example.org`). Replace it:
**Clients → `gallery-app` → Settings** → set **Valid redirect URIs** to
`https://<real-gallery-origin>/*` and **Web origins** to `https://<real-gallery-origin>`
→ **Save**. Login from the real front-end will fail with `invalid_redirect_uri`
until this matches.

1.4 **Retrieve client secrets out-of-band (if/when needed).** No secret is committed.
`gallery-api` is bearer-only and `gallery-app` is a public SPA, so neither needs a
secret today. When a confidential client is added later (e.g. an org-deployed
client per [ADR 0004](../docs/adr/0004-access-model-oauth-clients.md), or a
confidential `gallery-app` sibling), Keycloak generates the secret on client
creation — read it from **Clients → `<client>` → Credentials** and hand it to the
deployment team over a secure channel. Never paste it back into the repo.

1.5 **Verify the import structurally.** From a checkout of this repo you can assert
the flow shape and hardening landed as intended:

```bash
keycloak/verify-prod-realm.sh --offline   # asserts the JSON you imported; no network
```

For a deeper check against a *throwaway* instance (never the production one), see
[keycloak/README.md → Verifying the Gallery Ops flow](README.md#verifying-the-gallery-ops-flow).

---

## 2. Create ≥2 Gallery Ops admin accounts

Do this **twice** — the realm must have at least two admins before you consider
the bootstrap complete (see [§5](#5-operational-rules-and-recovery)). For each
account:

2.1 **Create the user.** Admin Console → realm `gallery` → **Users → Add user**:

- **Username** — the operator's work identifier (e.g. `alice.ops`).
- **Email** — their work email. Set **Email verified: On** (there is no SMTP, so
  Keycloak will not send a verification mail; leaving it Off can wedge login).
- **First name / Last name** — set both. If either is blank the login flow diverts
  to `VERIFY_PROFILE` on first sign-in. (This bit us in #95.)
- **Create.**

2.2 **Add the account to the Gallery Ops Organisation.** A Gallery Operator is, by
definition, a member of the **Gallery Ops** Organisation. **Organizations →
`gallery-ops` → Members → Add member** → select the user. (This is what puts
`org_id` into their token.)

2.3 **Assign the `admin` role.** **Users → `<the user>` → Role mapping → Assign
role** → filter by realm roles → select **`admin`** → **Assign**. That single
composite role grants every operator scope; do not hand-pick the granular
`admin:*` / `prompt:*` roles. Assign `organization-admin` **only** if this specific
person also needs the gallery-side Organisation-Admin flag (uncommon for Ops staff
— see the terms table in [§0](#0-before-you-start)).

2.4 **Do not set a password here if the operator will use a passkey.** Credential
enrollment is the operator's own action in [§3](#3-each-admin-enrolls-their-own-credential).
If you must set a temporary password (password+TOTP path), use **Credentials → Set
password**, leave **Temporary: On**, and communicate it over a secure channel — it
must satisfy the realm policy: **≥12 chars, with an uppercase, a lowercase, a digit,
a special char, and not equal to the username.**

---

## 3. Each admin enrolls their own credential

Login is **passkey OR password+TOTP** — two *alternative* branches, not layers. A
passkey satisfies login on its own (it is already MFA-strength); password+TOTP is
the recovery-grade alternative. Each operator enrolls their **own** credential;
an admin does not enroll another admin's passkey.

Enrollment happens at the account console:
`https://<keycloak-host>/realms/gallery/account`, signing in as the new account.

**Passkey (recommended):**

1. Sign in to the account console. On first sign-in with no credential yet, the
   flow prompts to register.
2. **Account console → Signing in → Passwordless → Set up passkey** (or complete
   the `webauthn-register-passwordless` prompt the login flow raises). Use the
   operator's platform authenticator or hardware security key. The realm requires
   an authenticator that **supports resident keys and user verification**.

**Password + TOTP (alternative / recovery-grade):**

1. Sign in with the temporary password from step 2.4; set a new password meeting
   the policy above.
2. The flow raises `CONFIGURE_TOTP` — scan the QR with an authenticator app (or use
   the manual secret) and enter the 6-digit code to bind the TOTP device.

> There is **no email-based reset** (`resetPasswordAllowed: false`, no SMTP). Losing
> *both* a passkey and the TOTP device means recovery via a second admin — see
> [§5](#5-operational-rules-and-recovery). Keep enrolled devices safe.

---

## 4. Verify one full end-to-end login per admin

For **each** enrolled admin, prove the whole path works — not just that the
credential registered:

1. Fresh browser session (incognito / cleared cookies), go to the real gallery
   front-end (or `https://<keycloak-host>/realms/gallery/account` if the SPA isn't
   deployed yet).
2. Enter the username/email (identity-first), then satisfy the credential:
   - **Passkey path:** you should reach the app with no password/OTP prompt.
   - **Password+TOTP path:** enter password, then the current TOTP code.
3. Confirm you land authenticated and, if checking the token, that it carries
   `org_id` for `gallery-ops` and `realm_access.roles` including `admin`.

Record who verified, for which account, and when. **At minimum one account must
have a fully verified end-to-end login before the realm is considered live**, and
you should verify all of them.

---

## 5. Operational rules and recovery

These rules live **here**, in the doc an operator actually reaches for during an
incident — not only in [ADR 0007](../docs/adr/0007-production-realm-config.md).

- **≥2 Gallery Ops admins at all times.** The `gallery` realm must never drop below
  two accounts holding `admin`. `admin` accounts have **no** email self-service
  reset and **no** lower-level break-glass, so a single admin is one lost device
  away from a locked realm. Before offboarding an admin or retiring an account,
  confirm another `admin` account exists and its owner has a working credential.

- **Recovery = second admin resets via the Admin Console.** If an operator loses
  *both* their passkey and their TOTP device, the **only** recovery is another
  Gallery Ops admin doing, in the Admin Console:
  1. **Users → `<locked user>` → Credentials** → delete the stale passkey / OTP.
  2. Either set a temporary password (**Temporary: On**, policy-compliant) **or**
     add the `webauthn-register-passwordless` required action so the user re-enrolls
     a passkey on next login (**Users → `<locked user>` → Details → Required user
     actions**).
  3. The recovered operator signs in and re-enrols their credential per
     [§3](#3-each-admin-enrolls-their-own-credential), then re-verifies per
     [§4](#4-verify-one-full-end-to-end-login-per-admin).

  There is no path below this. That is precisely why the ≥2-admins rule is not
  optional.

---

## Checklist

- [ ] `realm-export.prod.json` imported into the shared production instance (`organization` feature on).
- [ ] `gallery-app` redirect URI / web origin set to the real production SPA origin.
- [ ] ≥2 Gallery Ops admin accounts created, each a member of the `gallery-ops` Organisation and holding `admin`.
- [ ] Each admin has enrolled a credential (passkey, or password+TOTP).
- [ ] ≥1 account has a verified end-to-end login (verify all where possible).
- [ ] The ≥2-admins rule and second-admin recovery path are understood by the ops team.
