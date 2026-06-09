---
status: accepted
---

# MCP Server: Token-Forwarding Sidecar

The gallery exposes its prompt API over the Model Context Protocol (MCP) for chat
clients. We add a **thin sidecar MCP server** — its own deployable in this repo
(`gallery_mcp/`) — that translates MCP tool calls into ordinary gallery REST calls,
**forwarding the End User's bearer token unchanged**. The sidecar holds **no
authorization logic of its own**: the gallery validates the token and applies its
visibility + scope filter exactly as for any other API caller, so the gallery remains the
single enforcement point and the MCP surface can never reveal a prompt the REST API would
not. See [CONTEXT.md](../../CONTEXT.md) ("MCP server" vs "Integration") and ADR 0004 for
the underlying access model.

> **Package naming:** the local package is `gallery_mcp/` rather than `mcp/`. A `mcp/`
> directory at the project root would shadow the installed `mcp` SDK (`mcp.server.fastmcp`,
> `mcp.types`, etc.) in Python's import resolution, breaking all SDK imports.

## Scope of the first increment

- **Read-only, for now.** The MVP exposes only read tools — `search_prompts`,
  `get_prompt`, `list_featured`, `list_categories`, `list_tags` — each a 1:1 forward to an
  existing endpoint. **Write tools (create/edit/publish/rate) are planned for a later
  increment** and are out of scope here; the MVP exists to validate functionality and
  auth and to scope that follow-on work.
- **Scope read = what the caller may see.** Reads cover `published_public` *and* the
  caller's `published_org` prompts. ("Public" alone would be readable anonymously and
  would exercise no auth — the opposite of the MVP's goal.)
- **Auth = ADR 0004's v1 primary path.** An org-deployed confidential Keycloak client,
  authorization-code + PKCE, with the End User's own login. The resulting Keycloak access
  token (carrying `org_id` + scopes) flows through the gallery's existing
  `decode_and_verify` → `visibility_filter` path verbatim. The opaque API-key path is the
  documented fallback; per-user DCR remains the ADR 0004 upgrade path.

## Why this shape

- **Single enforcement point.** Because every tool call re-issues the End User's request
  against the gallery REST API, visibility and scope are enforced in exactly one place,
  with zero duplication. A bug in the MCP layer cannot widen access.
- **Crypto-free sidecar.** The sidecar does not verify signatures, audience, or expiry —
  it forwards the credential and lets the gallery (the existing validator) decide. It
  holds only the MCP-required discovery surface (`.well-known/oauth-protected-resource`
  advertising Keycloak) and translates the gallery's `401` into a spec-shaped
  `401 + WWW-Authenticate`. This keeps token validation in one place that cannot drift.
- **Same repo, separate deployable.** Shares CI, types, and review with the gallery
  (catching contract drift in one PR) while deploying and scaling independently.

## Considered alternatives

- **Embed MCP inside the FastAPI app** (one process, call `prompt_service` in-process).
  Rejected: couples the MCP protocol into the API service and opens a second code path
  into the visibility filter. The sidecar's extra hop is irrelevant at this scale.
- **Sidecar validates the JWT locally** (own JWKS/audience check before forwarding).
  Rejected: duplicates the validation logic ADR 0004 deliberately centralized, creating a
  second place auth can drift. Delegating costs one hop on bad tokens — accepted.
- **Auto-generate tools from `openapi.json`.** Rejected: leaks REST endpoint shapes as the
  tool surface and gives poor LLM ergonomics.
- **Separate repo.** Rejected for the MVP: duplicates tooling and makes gallery-contract
  drift harder to catch.

## Consequences

- Every MCP call is two hops (client → sidecar → gallery); fine at this scale, and the
  price of the single-enforcement-point property.
- A token the gallery would reject still costs one hop before rejection — accepted.
- The MCP server is gallery-side infrastructure, distinct from an "Integration" (the
  client). One MCP server; many Integrations.
