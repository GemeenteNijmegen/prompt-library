# Quickstart: how the pieces fit together

This doc is the 10-minute mental model for a new developer or PM, to read
before README.md (how to run it), ARCHITECTURE.md (how it's built), or
CONTEXT.md (the vocabulary). It answers one question: **what are the four things
people mean when they talk about "the gallery," and how do they talk to each other?**

## The four things

| Thing                          | What it is                                                                                                                                                                                                                                                                                                                                                                                          | Lives where                                                                                         |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| **Leiden AI Challenge**        | The umbrella platform/product. Has its own frontend (a SPA), its own repo, its own ADRs and issue tracker. The Prompt Gallery used to be built into it.                                                                                                                                                                                                                                             | A separate repo — not this one                                                                      |
| **Prompt Gallery** (this repo) | A standalone FastAPI REST API for storing, searching, and rating prompts. Was extracted out of the Leiden AI Challenge platform so it could be reused by other consumers too (see `PLAN.md`, "Extraction Plan"). Knows nothing about the platform's domain concepts — fields like `linked_challenge_id` and platform-specific roles were dropped during the extraction (see `PLAN.md` decision 2b). | This repo                                                                                           |
| **Keycloak**                   | The identity provider (IdP) shared by the platform and the gallery. One realm (`gallery`), issues OAuth/OIDC JWTs, federates each customer Organisation to its own Entra ID tenant. Neither the platform nor the gallery authenticates anyone itself — Keycloak does.                                                                                                                               | `keycloak/` in this repo (dev realm + prod template); the actual running instance is separate infra |
| **Chatbots / chat clients**    | Anything that calls the gallery's API on behalf of an End User instead of a browser: OpenWebUI, Copilot Enterprise, a custom internal chat client, or an LLM app connected via the gallery's MCP sidecar (`gallery_mcp/`).                                                                                                                                                                          | External to this repo; the gallery only defines how they authenticate                               |

The one-sentence version: **the Leiden AI Challenge platform's SPA, and various
chat clients, both call the Prompt Gallery API — and both authenticate through the
same Keycloak realm, never through the gallery or the platform directly.**

## How they connect

```
                         ┌──────────────────────────┐
                         │        Keycloak            │  ← IdP, one realm ("gallery")
                         │  Organizations (1 per      │     federates each org to its
                         │  customer), realm roles,   │     own Entra ID tenant
                         │  OAuth scopes, JWKS         │
                         └──┬───────────┬────────────┘
                     login  │           │  login
                            ▼           ▼
              ┌────────────────┐   ┌───────────────────────────┐
              │ Leiden AI      │   │ Chat clients               │
              │ Challenge SPA  │   │ • OpenWebUI (API key)       │
              │ (own repo,     │   │ • Copilot Enterprise (OAuth)│
              │ "gallery-app"  │   │ • Custom internal client    │
              │ Keycloak client│   │ • Claude/Cursor/etc. via    │
              └───────┬────────┘   │   gallery_mcp sidecar (OAuth)│
                      │            └───────────────┬─────────────┘
                      │ Bearer JWT                  │ Bearer JWT / API key
                      ▼                             ▼
              ┌───────────────────────────────────────────────┐
              │              Prompt Gallery API                 │  ← this repo
              │  FastAPI — one authorization path regardless     │
              │  of which door the request came through:         │
              │  JWT (JWKS-validated) or opaque pg_… key          │
              └───────────────────────────────────────────────┘
```

Three things fall out of this shape:

1. **The gallery never talks to Keycloak to authenticate a request.** It only
   fetches Keycloak's public keys (JWKS) once and verifies signatures locally.
   Keycloak is the login page; the gallery is just a JWT verifier.
2. **The platform SPA and chat clients are peers, not a hierarchy.** Both are
   just OAuth clients registered in the same Keycloak realm. The gallery treats
   an End User logging in through the Leiden AI Challenge SPA exactly the same as
   the same End User's message going through OpenWebUI — same `sub`, same
   `org_id`, same visibility rules.
3. **`gallery_mcp/` is gallery-side infrastructure, not a chatbot.** It's a thin
   sidecar that lets MCP-speaking clients (Claude Desktop, MCP Inspector, etc.)
   call the gallery's read API. It forwards the caller's token unchanged and
   validates nothing itself — the gallery is still the only enforcement point.
   See `gallery_mcp/README.md` and ADR 0005.

## Three ways a chat client can reach the gallery

Not every chatbot integrates the same way — this is usually the first thing a
new dev needs to disambiguate when someone asks "how does chatbot X talk to the
gallery?"

| Path                               | Who it's for                                                                            | How auth works                                                                                                                                                 | Setup cadence                                               |
| ---------------------------------- | --------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| **Org-deployed OAuth client**      | Copilot Enterprise, a custom internal chat client, or an MCP client (via `gallery_mcp`) | Confidential client + PKCE, registered once in Keycloak per Organisation deployment. Each End User logs in themselves through it.                              | Once per Organisation, by a Gallery Operator (see ADR 0004) |
| **API key (opaque `pg_…` secret)** | OpenWebUI, CI pipelines, scripts, ad-hoc tooling — anything that can't do OAuth         | End User (or an Organisation Admin, for a headless/service identity) self-serves a key via `POST /api/v1/me/api-keys`. Sent as `Authorization: Bearer pg_...`. | Any time, self-service                                      |
| **First-party SPA**                | The Leiden AI Challenge platform's own frontend                                         | Public client + PKCE (`gallery-app`), same Keycloak realm                                                                                                      | Once, by a Gallery Operator                                 |

All three converge on one `AuthenticatedUser` inside the gallery (`src/middleware/auth.py`)
— there's exactly one authorization path no matter which door the request came in.

## The actor model, in one paragraph

An **Organisation** (a customer, or "Gallery Ops" itself) federates to one Entra
tenant. **End Users** belong to exactly one Organisation and are the people
logging in. An **Organisation Admin** is an End User with an extra role for
their own org. An **Integration** is the software acting on an End User's
behalf — an OAuth client or an API key. Prompts are visible according to a
three-state model (`draft` / `published_org` / `published_public`) that's
independent of which Integration is asking. Full definitions, including why
"customer" is deliberately avoided as a term: **[CONTEXT.md](../CONTEXT.md)**.

## Where to go next

| Question                                                                       | Doc                                                                                                            |
| ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| How do I run the gallery locally?                                              | [README.md](../README.md) — Quick start / Docker section                                                       |
| How do I run it with real Keycloak locally?                                    | [README.md](../README.md) §"Docker" (`--profile keycloak`), [keycloak/README.md](../keycloak/README.md)        |
| How is the code laid out? What are the design decisions?                       | [ARCHITECTURE.md](../ARCHITECTURE.md)                                                                          |
| What do "Organisation," "End User," "visibility" etc. mean precisely?          | [CONTEXT.md](../CONTEXT.md)                                                                                    |
| Why Keycloak, and how does login/federation work?                              | [ADR 0003](adr/0003-identity-provider-keycloak.md)                                                             |
| How do OAuth clients and API keys actually get set up?                         | [ADR 0004](adr/0004-access-model-oauth-clients.md)                                                             |
| How does the MCP sidecar work, and how do I connect an MCP client?             | [gallery_mcp/README.md](../gallery_mcp/README.md), [ADR 0005](adr/0005-mcp-server-token-forwarding-sidecar.md) |
| I'm integrating a new SPA/browser client against Keycloak — what will bite me? | [keycloak/README.md](../keycloak/README.md) §"Integrating a browser SPA"                                       |
| How does production Keycloak get bootstrapped?                                 | [keycloak/PRODUCTION.md](../keycloak/PRODUCTION.md), [ADR 0007](adr/0007-production-realm-config.md)           |
| What decisions were made during the extraction from the platform, and why?     | [PLAN.md](../PLAN.md)                                                                                          |

## Fastest path to "I see it working"

```bash
# From this repo:
cp .env.example .env
# uncomment the Keycloak block in .env.example first, then:
docker compose --profile dev --profile keycloak up
```

Then, in another terminal:

```bash
# Log in as a seeded contributor (org-a) and hit the API:
TOKEN=$(python scripts/keycloak_token.py --grant password --username alice --password dev)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/me
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/prompts
```

That `alice` login is standing in for what both the Leiden AI Challenge SPA and
any chat client do at runtime: redirect to Keycloak, come back with a JWT, call
the gallery. See [keycloak/README.md](../keycloak/README.md) for the full seeded-user
table and what each persona can do.
