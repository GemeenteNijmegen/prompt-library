# gallery_mcp — Prompt Gallery MCP sidecar

A thin **token-forwarding MCP server** that exposes the gallery's read API over the
Model Context Protocol to chat clients. It holds **no authorization logic**: it captures
the caller's bearer token, forwards it unchanged to the gallery REST API, and lets the
gallery validate signature/audience/expiry and apply its visibility + scope filter. The
gallery stays the single enforcement point.

Authoritative design: **[ADR 0005](../docs/adr/0005-mcp-server-token-forwarding-sidecar.md)**
(sidecar shape) and **[ADR 0004](../docs/adr/0004-access-model-oauth-clients.md)** (access model).
This README is the operational "how do I run and use it" companion.

## The three parties

| Party | Role (RFC 9728 / MCP auth spec) | In this repo |
|---|---|---|
| **MCP client** | OAuth *client* — does the login, holds the token | MCP Inspector, `mcp-remote`, Claude Desktop connector, VS Code MCP, … |
| **gallery_mcp sidecar** | Protected *resource server* — advertises the auth server, forwards tokens | `gallery_mcp/` (this package) |
| **Keycloak** | *Authorization server* — mints the token | realm `gallery` |

The sidecar does **zero crypto** — no signature/audience/expiry check. It only advertises
discovery metadata and forwards the credential; the gallery decides (ADR 0005 invariant).

## How the OAuth2 flow works

```
1. MCP client → sidecar /mcp                          (no token)
2. sidecar → 401 + WWW-Authenticate:
        Bearer resource_metadata="https://<sidecar>/.well-known/oauth-protected-resource"
3. client GETs that metadata →
        { resource: <MCP_RESOURCE_URL>,
          authorization_servers: [ <KEYCLOAK_REALM_URL> ],
          bearer_methods_supported: ["header"] }
4. client GETs Keycloak's .well-known/oauth-authorization-server   (Keycloak serves natively)
        → authorize + token endpoints, PKCE support
5. client runs authorization-code + PKCE against Keycloak
        → browser opens → real user logs in (passkey / password+TOTP, or Entra federation)
        → access token:  aud=prompt-gallery-api, org_id, realm_access.roles
6. client calls sidecar tools with  Authorization: Bearer <token>
7. sidecar forwards the header UNCHANGED to the gallery REST API
8. gallery validates + applies visibility filter.  A gallery 401 is re-shaped by the
   sidecar into a spec 401 + WWW-Authenticate, which re-triggers the auth dance.
```

Steps 1–3 and 8 are `server.py`'s `_AuthMiddleware` + the `/.well-known/oauth-protected-resource`
route. Step 7 is the forwarding invariant.

### The one divergence from "zero-config MCP": no Dynamic Client Registration

The MCP spec assumes step 4→5 includes **DCR** — the client auto-registers at Keycloak's
`registration_endpoint` and receives a fresh `client_id`. **v1 does not enable DCR**
(ADR 0004: "No clients are dynamically registered in v1"; it is the documented upgrade path).

Consequence:
- An MCP client you can configure with a **static `client_id`** works today → pre-register
  one public client (see checklist step 2).
- An MCP client that **only** supports DCR will fail at registration until DCR is enabled
  (a Keycloak-config change with client policies, not a code change).

## Scope of the current increment

**Read-only.** Tools: `search_prompts`, `get_prompt`, `list_featured`, `list_categories`,
`list_tags` — each a 1:1 forward to a gallery endpoint. Reads cover `published_public` plus
the caller's own `published_org` prompts, filtered by the gallery per the token's `org_id`.
Write tools (create/edit/publish/rate) are a later increment (ADR 0005 §"Scope of the first
increment"). `prompt:read` is a default scope, so a plain login already satisfies every tool.

## Configuration

Env vars (see [`.env.prod.example`](.env.prod.example); defaults in `config.py`):

| Var | Meaning | Production note |
|---|---|---|
| `GALLERY_API_URL` | Gallery REST API base URL | Internal URL OK (sidecar→gallery hop) |
| `MCP_HOST` / `MCP_PORT` | Bind address / port | Default `0.0.0.0:8001` |
| `MCP_RESOURCE_URL` | Public URL of **this** sidecar | Externally reachable; the `resource` id in discovery |
| `KEYCLOAK_REALM_URL` | Auth server advertised to clients | **Must equal token `iss` and the API's `JWT_ISSUER`, byte-for-byte**; browser-reachable |
| `GALLERY_REQUEST_TIMEOUT` | Upstream timeout (s) | Default `30.0` |

Run: `python -m gallery_mcp` (serves streamable-HTTP at **`/mcp`**). Also runs as a container
under the `full`/`dev` compose profiles on port 8001.

## Production setup checklist

- [ ] **1. Gallery + Keycloak are up** with realm `gallery` imported (`keycloak/PRODUCTION.md`),
      and at least one login-capable user exists (federated Entra user, or a local Gallery Ops
      account with a passkey or password+TOTP enrolled).
- [ ] **2. Register the MCP OAuth client.** Import `keycloak/templates/mcp-public-client.json`
      (public, PKCE-S256). Set its `redirectUris` to the callback your MCP tool actually uses —
      pin the port if the tool allows (e.g. `mcp-remote --callback-port 6274`). If login later
      fails with `invalid_redirect_uri`, copy the exact URI from Keycloak's error page into the
      client and retry.
- [ ] **3. Configure the sidecar env** from `.env.prod.example`. Double-check
      `KEYCLOAK_REALM_URL` == the API's `JWT_ISSUER` == the token `iss` (all identical), and that
      `MCP_RESOURCE_URL` is the externally-reachable sidecar URL.
- [ ] **4. Start the sidecar** (`python -m gallery_mcp` or the compose profile).
- [ ] **5. Smoke-test discovery (no auth needed):**
      `curl https://<sidecar>/.well-known/oauth-protected-resource` → confirm it lists your
      `MCP_RESOURCE_URL` and `KEYCLOAK_REALM_URL`. `curl https://<sidecar>/health` → `{"status":"ok"}`.
- [ ] **6. Confirm the unauthenticated 401:** `curl -i https://<sidecar>/mcp` → expect
      `401` with a `WWW-Authenticate: Bearer resource_metadata="…"` header.
- [ ] **7. Connect a real MCP client** (see below), configured with `client_id=mcp-client` and
      the sidecar URL `https://<sidecar>/mcp`. Complete the browser login as a real user.
- [ ] **8. Exercise a tool** (e.g. `search_prompts`) and confirm results are scoped to that
      user's `org_id` (they see `published_public` + their own org's `published_org`, nothing else).

## Driving it with a real MCP client

Both of these implement the full discovery + auth-code + PKCE + loopback-redirect dance and let
you set a static `client_id`:

- **MCP Inspector:** `npx @modelcontextprotocol/inspector` → transport *Streamable HTTP* →
  URL `https://<sidecar>/mcp` → it walks discovery, opens Keycloak for login, then lists tools.
- **mcp-remote** (bridges a remote HTTP MCP server into a stdio client like Claude Desktop):
  point it at `https://<sidecar>/mcp` and pin `--callback-port` to a port you registered.

Once the user is authenticated the client sends `Authorization: Bearer <token>` on every tool
call; the sidecar forwards it; the gallery enforces visibility.

## Gotchas

- **Issuer must match in three places.** `KEYCLOAK_REALM_URL` (here), `JWT_ISSUER` (gallery API),
  and the token `iss` must be identical strings. A mismatch → every token rejected with a
  confusing "Invalid issuer". Pin Keycloak's `KC_HOSTNAME` and copy it verbatim everywhere.
- **`MCP_RESOURCE_URL` must be externally reachable.** It is the `resource` identifier and appears
  in `WWW-Authenticate`; if the MCP client can't resolve it, discovery loops fail. It is
  deliberately *not* the same string as the API audience `prompt-gallery-api` — the sidecar checks
  nothing, and the `gallery-defaults` scope stamps `prompt-gallery-api` into `aud` regardless.
- **Read-only for now.** No write path through MCP until the write-tools increment lands.
- **DCR-only clients won't connect** in v1 (see above).
- **The sidecar validates nothing** — a bad token still costs one hop to the gallery before
  rejection. That's the deliberate price of the single-enforcement-point design (ADR 0005).
