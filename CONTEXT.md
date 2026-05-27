# Prompt Gallery — Context & Vocabulary

This file is the canonical reference for the gallery's domain vocabulary. When ADRs, PLAN.md, code, and conversations use terms like "Organisation" or "End User," they mean what is defined here.

If a term in this file conflicts with something elsewhere, **this file wins** and the other reference should be updated.

## Actor model

The gallery's identity and authorization design recognises five actor concepts. Four of them are people-or-organisations (the *who*); one is software acting on behalf of a person (the *how*).

| Term | Meaning | IdP representation (Keycloak) | Identity source |
|---|---|---|---|
| **Gallery Operator** | Staff who operate the gallery service and Keycloak realm configuration. Holds `admin:*` scopes. | User in the "Gallery Ops" Organisation | Local Keycloak account (no Entra federation) |
| **Organisation** | A logical organisation that uses the gallery. Federates to exactly one Entra tenant. May be a paying customer, a partner, an internal team, or the Gallery Ops bootstrap org. | Keycloak Organization (v26+) | One Entra tenant per Organisation (or local users, for Gallery Ops) |
| **Organisation Admin** | A designated person inside an Organisation who manages that org's users and gallery-scope assignments in the Keycloak admin console. | Keycloak `organization-admin` role scoped to that Organisation | A federated Entra End User with the additional Keycloak role |
| **End User** | An individual person authenticating to the gallery. Belongs to exactly one Organisation. | Keycloak user federated from that Organisation's Entra (or local, for Gallery Operators) | Entra (or local) |
| **Integration** | Software acting on behalf of an End User. Either an MCP-registered OAuth client (Claude, Cursor, etc.) or an API-key-style offline-token client. | OAuth client (DCR-registered or first-party) tied to a specific End User's offline token / refresh chain | Derives identity from the End User who installed it |

## Notes on the model

- **"Gallery Ops" is itself an Organisation in Keycloak terms.** It is not special-cased in the realm structure; it just happens to use local Keycloak users instead of Entra federation. From Keycloak's perspective the layer-count is flat: one realm, N Organisations, one of which is Gallery Ops.

- **There is no separate "service account" actor type.** A customer's CI pipeline that calls the gallery is a *headless* End User (a local Keycloak user inside the Organisation with no human behind it) with an Integration attached (an API key / offline token). Modelled identically to a human End User with an API key. Headless End Users and their keys are provisioned by Organisation Admins **directly in Keycloak admin**, not via the gallery API. The gallery's `/me/api-keys` endpoints cover only "I want a key for my own End User identity" — typically used by Organisation Admins or developers granted the `apikey:create` scope for their own use.

- **Organisation Admin is a role, not a separate actor type.** An Organisation Admin is an End User with an extra Keycloak role attached that lets them administer their own org. Same JWT shape, same auth path — they can also use the gallery as a normal End User.

- **The word "customer" is intentionally avoided.** Not every Organisation is a commercial customer (Gallery Ops, partner teams, dogfood orgs, open-source community orgs). Whether an Organisation is a paying customer is a billing-system concern, not an identity-model concern.

- **End Users do not normally see the word "Organisation" in the gallery UI.** They log in with their work email; routing to their Organisation is implicit (email-domain mapping — see ADR 0003). The term lives in admin UI and docs, not in the user-facing product.

## Visibility model

Prompts have a visibility state that determines who can see them. The state is independent from scope-based authorization: scopes gate *verbs* (read, write, publish, etc.), and visibility is a row-level filter applied uniformly to read endpoints regardless of which scopes the caller holds.

| Prompt state | Visible to |
|---|---|
| `draft` | The author + Organisation Admins of the author's Organisation |
| `published_org` | All End Users in the author's Organisation |
| `published_public` | All End Users across all Organisations |

The row-level filter applied to every read query is conceptually:

```sql
WHERE visibility = 'published_public'
   OR (visibility = 'published_org' AND org_id = :caller_org_id)
   OR (status = 'draft' AND (author_id = :caller_id
                             OR :caller_is_org_admin_of_author_org))
```

`org_id` comes from the JWT (see ADR 0004 for the JWT contract). `author_id` is on the prompt row. `:caller_is_org_admin_of_author_org` is derived from the caller's roles.

## Publish workflow

There are two distinct "publish" actions, with different blast radii:

- **`prompt:publish` — publish to own Organisation.** Promotes a draft to `published_org`. Available to End Users with the scope (typically a small writer/publisher group, configurable per Organisation by the Organisation Admin).
- **`prompt:publish:public` — publish to all Organisations.** Promotes a prompt to `published_public`. Restricted to Gallery Operators only. Customer Organisations cannot self-serve public publication; they can request public promotion of one of their `published_org` prompts, but the actual transition is a Gallery Operator curation action.

## Related documents

- ADR 0003 — Identity Provider: Keycloak
- ADR 0004 — Access Model: MCP + DCR with API-key Fallback
- PLAN.md — Decision log and API specification
