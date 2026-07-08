# Keep a surrogate user PK (external_id = sub); solve identity correlation at the API boundary

## Status

accepted

## Context & Decision

The gallery's `User` has a surrogate integer PK (`users.id`) with `external_id` holding
the Keycloak `sub` as a unique natural key; `Prompt.creator_id` FKs to `users.id`. A
consuming platform (Leiden AI Challenge) hit a wall: its SPA holds the token `sub` but
the prompt payload exposes only the internal `creator_id`, so the client could not answer
"is this prompt mine?" — the three namespaces (consumer-local id, `sub`, gallery
`creator_id`) don't correlate. See platform ADR 0002.

This raised the question: should the gallery collapse the two identities and make the
Keycloak `sub` the user PK? **We decided no — keep the surrogate PK.** The problem was a
*serialization* leak (handing clients an internal PK they can't resolve), not an identity
*modelling* problem. We fix it at the boundary, and keep the identity model intact.

**We decided two things:**

1. **Retain the surrogate integer PK with `external_id` = `sub`.** The indirection is a
   feature: a `sub` is stable *until* a realm re-import / user re-creation / IdP migration
   changes it — with `external_id` as a column that's a one-field re-map, but as a PK it
   orphans every FK across prompts, ratings, events, and api-keys. It also lets non-`sub`
   principals (opaque API-key identities, headless End Users — see CONTEXT.md and ADR
   0004) share one uniform owner model. Correlation is solved where a client legitimately
   needs it, at serialization, not by promoting the IdP's key to our PK.

2. **Declare a per-prompt capability set on the API payload.** The prompt schema gains
   server-computed booleans — `can_edit`, `can_delete`, `can_publish`, `can_feature` —
   derived from the caller's ownership (`creator_id == caller.id`) and scopes
   (`prompt:write`, `prompt:publish`, `prompt:moderate`). Consumers render affordances
   straight from these flags and never re-implement the authorization rule client-side.
   This subsumes the owner-vs-moderator distinction (`can_edit = owner || moderator`).

## Considered alternatives

- **Make `sub` the user PK (collapse the namespaces).** Rejected: fragile to `sub`
  churn, awkward for non-`sub` principals, and — once capability flags exist — buys the
  client nothing, since it no longer compares ids at all.
- **Expose `creator_external_id` (the sub) and let clients compare.** Rejected: still
  re-implements the ownership + moderate rule in every consumer; capability flags put the
  rule in one place (here).

## Consequences

- The prompt read schema/serialization gains caller-dependent fields, so identical prompts
  serialize differently per caller — response caching must key on the caller, not just the
  prompt id.
- Consuming apps depend on the capability flags for affordance rendering; adding a new
  prompt action means adding its flag here.
