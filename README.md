# Prompt Gallery API

Standalone REST API for managing, searching, and rating AI prompts. Built with FastAPI + SQLAlchemy + Pydantic v2.

> New here? [docs/QUICKSTART.md](docs/QUICKSTART.md) explains how this repo, the Leiden AI Challenge platform, Keycloak, and chat clients (OpenWebUI, Copilot Enterprise, MCP clients) fit together — read that before the rest of this file.

## Quick start

```bash
cp .env.example .env
# Set JWT_SECRET_KEY in .env for dev mode
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --reload
```

Interactive docs: http://localhost:8000/docs

## Docker

Run with Docker Compose:

```bash
docker-compose up
```

This starts the API, PostgreSQL, and Redis. Configuration is read from `.env`.

There are several Docker Compose profiles:

| Profile | What starts | Use case |
|---|---|---|
| `full` (default) | Postgres + Redis + app | Production-like |
| `dev` | Postgres + Redis + app (hot-reload) | Day-to-day development |
| `dev` + `keycloak` | + local Keycloak v26 (RS256) | Full local SSO, smoke testing |
| `simple` | app only (SQLite) | Lightweight / no infra |
| `embeddings` | Postgres + Redis + app (model bundled) | Real semantic search |

**Hot-reload dev (HS256 stub tokens):**

```bash
docker compose --profile dev up
```

**Hot-reload dev with local Keycloak (RS256):**

```bash
# Uncomment the Keycloak block in .env.example and copy to .env first
docker compose --profile dev --profile keycloak up
```

Keycloak is available at http://localhost:8080 (admin / admin). The gallery realm is imported automatically on first start (~15–25 s cold boot). Once the stack is up, fetch a token and hit the API:

```bash
# RS256 token via service account (gallery-test-client):
TOKEN=$(python scripts/keycloak_token.py)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/me

# Or as the dev user (devuser / devpass):
TOKEN=$(python scripts/keycloak_token.py --grant password --username devuser --password devpass)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/me
```

**Lightweight (SQLite, no external services):**

```bash
docker compose --profile simple up
```

**Real semantic search with the bundled ML model:**

```bash
docker compose --profile embeddings up
```

This starts Postgres, Redis, and the `app-with-embeddings` image which has `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` weights pre-baked in. The default (`full`) profile uses the slim image with `EMBEDDING_USE_FAKE=false` (fastembed downloads on first use if model is not cached).

Build and run the image directly:

```bash
# Slim image (no bundled model weights):
docker build --target app -t prompt-gallery .

# Production image (model weights bundled):
docker build --target app-with-embeddings -t prompt-gallery-full .

docker run -p 8000:8000 prompt-gallery
```

The `app-with-embeddings` image is automatically published to GHCR on each release. The slim `app` image is used for CI tests. See GitHub Actions workflow for registry details.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

### Smoke tests (live Keycloak + gallery API)

The smoke tests in `tests/smoke/` require a real running stack. They are **skipped automatically** in normal `pytest` runs unless you export both env vars below.

**Step 1 — start Keycloak** (no Docker needed; use the Keycloak zip):

```bash
# Download once:
curl -LO https://github.com/keycloak/keycloak/releases/download/26.2.5/keycloak-26.2.5.zip
unzip keycloak-26.2.5.zip

# Start with the dev realm pre-loaded:
KC_BOOTSTRAP_ADMIN_USERNAME=admin \
KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
KC_HTTP_ENABLED=true \
KC_HOSTNAME_URL=http://localhost:8080 \
  keycloak-26.2.5/bin/kc.sh start-dev \
    --import-realm \
    --import-realm-file keycloak/realm-export.json
```

Keycloak is ready when `http://localhost:8080/health/ready` returns `{"status":"UP"}` (cold start ~15–25 s).

**Step 2 — start the gallery API** with RS256 mode enabled:

```bash
JWKS_URI=http://localhost:8080/realms/gallery/protocol/openid-connect/certs \
JWT_ISSUER=http://localhost:8080/realms/gallery \
JWT_AUDIENCE=prompt-gallery-api \
ENVIRONMENT=development \
EMBEDDING_USE_FAKE=true \
  uvicorn src.main:app --port 8000
```

**Step 3 — run the smoke tests:**

```bash
KEYCLOAK_URL=http://localhost:8080 \
GALLERY_API_URL=http://localhost:8000 \
  pytest tests/smoke -m smoke -v
```

What the smoke tests verify:
- A real RS256 token (client-credentials grant from `gallery-test-client`) is accepted by `GET /me` → 200.
- A stale HS256 token is rejected with 401 when `JWKS_URI` is active.
- A password-grant RS256 token for `devuser` / `devpass` is also accepted.

You can also get a token manually for `curl`:

```bash
# client-credentials (service account):
python scripts/keycloak_token.py

# password grant (dev user):
python scripts/keycloak_token.py --grant password --username devuser --password devpass
```

## MCP sidecar

The `gallery_mcp` package is a token-forwarding MCP sidecar (see ADR 0005). It exposes the gallery's `search_prompts` tool over the [Model Context Protocol](https://modelcontextprotocol.io/) so AI assistants can search prompts directly. It holds zero authorization logic — your bearer token is forwarded unchanged to the gallery, which enforces all visibility rules.

### Start

Requires the gallery API to be running first (`uvicorn src.main:app --reload` or `docker compose --profile dev up`).

```bash
python -m gallery_mcp
# Serving on http://0.0.0.0:8001
```

> **Python 3.14 users:** `uvloop` 0.22.1 (installed by `uvicorn[standard]`) tops out at Python 3.13. The sidecar passes `loop="asyncio"` explicitly so uvloop is bypassed — no action needed.

### Health check

```bash
curl http://localhost:8001/health
# {"status":"ok"}
```

No response (connection accepted but silent) usually means a stale process is still bound to port 8001:

```bash
lsof -ti :8001 | xargs kill -9 2>/dev/null
python -m gallery_mcp
```

### Verify the tool end-to-end

The gallery must be in **stub auth mode** (`JWT_SECRET_KEY` set, `JWKS_URI` empty — the default `.env`). If you recently changed `.env`, reload the gallery before testing.

```bash
# Mint a short-lived HS256 token and call search_prompts
TOKEN=$(python scripts/dev_token.py --scope prompt:read) && \
curl -s -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_prompts","arguments":{"query":"test","per_page":5}}}' | jq .
```

Expected: a JSON-RPC result with a `content[0].text` containing the gallery's paginated response. A `401 Unauthorized` in the error text means the gallery rejected the token — check that `JWKS_URI` is unset and restart the gallery.

### Connect MCP Inspector

[MCP Inspector](https://github.com/modelcontextprotocol/inspector) supports two modes.

#### Option A — HS256 stub token (no Keycloak needed)

Start the gallery in dev/stub-auth mode (`JWKS_URI` empty, `JWT_SECRET_KEY` set):

```bash
npx @modelcontextprotocol/inspector
```

In Inspector:
1. Transport: **Streamable HTTP**, URL: `http://localhost:8001/mcp`
2. Add header `Authorization: Bearer <token from dev_token.py>`

#### Option B — Full OAuth flow with local Keycloak

Start the full stack with Keycloak:

```bash
docker compose --profile full --profile keycloak up --build -d
```

Run Inspector:

```bash
npx @modelcontextprotocol/inspector
```

Inspector discovers the Keycloak realm automatically via
`/.well-known/oauth-protected-resource` and redirects you through the
authorization-code + PKCE flow. When Keycloak's login page appears, use
any gallery-realm user — **not** the Keycloak admin account:

| username | password | org |
|----------|----------|-----|
| `alice`  | `dev`    | org-a |
| `bob`    | `dev`    | org-b |
| `carol`  | `dev`    | org-b |
| `dave`   | `dev`    | — |

> The `mcp-inspector` client is pre-registered in `keycloak/realm-export.json`
> as a public client (`publicClient: true`, redirect URI `http://localhost:6274/*`).
> No client secret is required. Inspector's DCR attempt will fail (open registration
> is disabled), but the pre-registered client makes the auth-code flow work.

After login the tool list appears. Call `search_prompts` to verify the full
chat-client → MCP sidecar → gallery round-trip.

### OAuth discovery

The sidecar is a spec-compliant OAuth resource server. An OAuth-capable MCP client can discover the Keycloak realm automatically:

```bash
curl -s http://localhost:8001/.well-known/oauth-protected-resource | jq .
# {
#   "resource": "http://localhost:8001",
#   "authorization_servers": ["http://localhost:8080/realms/nijmegen"],
#   "bearer_methods_supported": ["header"]
# }
```

A request with a missing or gallery-rejected token returns `401` with a `WWW-Authenticate` header pointing at this document, so the client knows where to start the authorization-code + PKCE flow.

Configure the two new environment variables (or `.env`) to match your deployment:

| Variable | Default | Purpose |
|---|---|---|
| `MCP_RESOURCE_URL` | `http://localhost:8001` | Public URL of this sidecar — used as the `resource` identifier |
| `KEYCLOAK_REALM_URL` | `http://localhost:8080/realms/gallery` | Advertised authorization server |

### Running MCP unit tests

```bash
pytest tests/test_mcp_search_prompts.py tests/test_mcp_oauth_discovery.py -v
```

These tests stub the gallery HTTP call with `respx` and run without a live stack.

## Authentication

All protected endpoints use `Authorization: Bearer <jwt>`. See ADR 0003 (identity provider: Keycloak) and ADR 0004 (access model) for the full design.

**Production mode (Keycloak / JWKS):** Set `JWKS_URI` to the realm's JWKS endpoint (`https://<keycloak-host>/realms/<realm>/protocol/openid-connect/certs`), `JWT_ISSUER` to the realm URL (`https://<keycloak-host>/realms/<realm>`), and `JWT_AUDIENCE` to the configured resource-server audience (default `prompt-gallery-api`). Tokens must be RS256-signed.

**Dev / testing mode (HMAC):** Set `JWT_SECRET_KEY` in `.env` and leave `JWKS_URI` empty. Tokens are HS256-signed with the shared secret. Hard-blocked when `ENVIRONMENT=production`.

To mint a token for local `curl` testing:

```bash
python scripts/dev_token.py --scope prompt:read prompt:create
# prints a short-lived HS256 Bearer token; refuses to run when ENVIRONMENT=production
```

## API prefix

All routes are under `/api/v1/`. Health: `GET /api/v1/health`.

## Environment variables

| Variable               | Default                     | Purpose                                                            |
| ---------------------- | --------------------------- | ------------------------------------------------------------------ |
| `DATABASE_URL`         | `sqlite:///data/gallery.db` | DB connection                                                      |
| `ENVIRONMENT`          | `development`               | `development` / `production` / `testing`                           |
| `JWT_SECRET_KEY`       | ``                          | HMAC secret for dev/test (leave unset in prod; hard-blocked in production)             |
| `JWKS_URI`             | ``                          | OIDC JWKS endpoint (prod). Keycloak: `…/realms/<realm>/protocol/openid-connect/certs`  |
| `JWT_ISSUER`           | ``                          | Expected `iss` claim. Keycloak: `…/realms/<realm>` (no trailing slash). Required in prod. |
| `JWT_AUDIENCE`         | `prompt-gallery-api`        | Expected `aud` claim; gallery enforces strict containment                              |
| `JWKS_CACHE_TTL_SECONDS` | `3600`                    | How long fetched JWKS is cached; unknown `kid` forces a one-shot refetch               |
| `JWT_LEEWAY_SECONDS`   | `60`                        | Clock-skew tolerance for `exp`/`nbf` checks                                            |
| `CORS_ORIGINS`         | `http://localhost:5173`     | Comma-separated allowed origins (gallery SPA only; org-deployed chat clients are server-to-server and don't need CORS) |
| `STORAGE_BACKEND`      | `local`                     | `local` or `s3`                                                    |
| `STORAGE_LOCAL_PATH`   | `./uploads`                 | Local file upload directory                                        |
| `S3_BUCKET`            | ``                          | S3 bucket name (when `STORAGE_BACKEND=s3`)                         |
| `S3_REGION`            | `eu-west-1`                 | AWS region                                                         |
| `S3_ACCESS_KEY`        | ``                          | AWS access key                                                     |
| `S3_SECRET_KEY`        | ``                          | AWS secret key                                                     |
| `REDIS_URL`            | ``                          | Redis URL for caching (optional; uses in-memory TTLCache if unset) |
| `RATE_LIMIT_ANONYMOUS` | `30`                        | Requests/min per IP for unauthenticated callers                    |
| `RATE_LIMIT_USER`      | `120`                       | Requests/min per End User (`sub`)                                  |
| `RATE_LIMIT_CLIENT`    | `600`                       | Requests/min per OAuth client (`azp`)                              |
| `RATE_LIMIT_ORG`       | `1200`                      | Requests/min per Organisation (`org_id`)                           |
| `MAX_UPLOAD_SIZE`      | `5242880`                   | Max upload file size in bytes (default: 5 MB)                      |
| `LOG_LEVEL`            | `info`                      | Log verbosity: `debug`, `info`, `warning`, `error`                 |
| `EMBEDDING_MODEL`      | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Sentence embedding model for semantic search                  |
| `EMBEDDING_USE_FAKE`   | `false`                     | Use deterministic fake embedder (for dev/test; always set in CI)   |

See `.env.example` for the full variable list.

## Endpoints summary

| Method | Path                           | Auth                    | Description                           |
| ------ | ------------------------------ | ----------------------- | ------------------------------------- |
| GET    | `/api/v1/health`               | None                    | Liveness + DB check                   |
| GET    | `/api/v1/me`                   | Bearer                  | Current user profile                  |
| POST   | `/api/v1/me/api-keys`          | `apikey:create`         | Issue an API key (offline token) for self |
| GET    | `/api/v1/me/api-keys`          | Bearer                  | List own API keys                     |
| DELETE | `/api/v1/me/api-keys/{id}`     | Bearer                  | Revoke an own API key                 |
| GET    | `/api/v1/prompts`              | Optional                | List/search prompts                   |
| GET    | `/api/v1/prompts/featured`     | Optional                | Featured prompts                      |
| GET    | `/api/v1/prompts/{id}`         | Optional                | Prompt detail                         |
| POST   | `/api/v1/prompts`              | `prompt:create`         | Create prompt                         |
| PATCH  | `/api/v1/prompts/{id}`         | `prompt:write`          | Update prompt                         |
| POST   | `/api/v1/prompts/{id}/use`     | None                    | Increment use count                   |
| POST   | `/api/v1/prompts/{id}/rate`    | `prompt:rate`           | Submit rating                         |
| GET    | `/api/v1/prompts/{id}/rate`    | `prompt:rate`           | Get own rating                        |
| GET    | `/api/v1/prompts/{id}/ratings` | None                    | Rating stats                          |
| GET    | `/api/v1/categories`           | None                    | List categories                       |
| POST   | `/api/v1/categories`           | `admin:manage_taxonomy` | Create category                       |
| GET    | `/api/v1/categories/{id}`      | None                    | Category detail                       |
| PATCH  | `/api/v1/categories/{id}`      | `admin:manage_taxonomy` | Update category                       |
| DELETE | `/api/v1/categories/{id}`      | `admin:manage_taxonomy` | Soft-delete category                  |
| GET    | `/api/v1/tags`                 | None                    | List tags                             |
| POST   | `/api/v1/tags`                 | `admin:manage_taxonomy` | Create tag                            |
| GET    | `/api/v1/tags/{id}`            | None                    | Tag detail                            |
| DELETE | `/api/v1/tags/{id}`            | `admin:manage_taxonomy` | Soft-delete tag                       |
| POST   | `/api/v1/uploads/images`       | `prompt:image`          | Upload an image (multipart, max 5 MB) |
| DELETE | `/api/v1/uploads/images/{key}` | `prompt:image`          | Delete an uploaded image              |

## Status transitions

Valid prompt status graph: `draft → published_org → published_public → archived → draft` (restore).  
`prompt:publish` is required for own-Organisation transitions; `prompt:publish:public` (Gallery Operators only) is required for cross-Organisation promotion.

## Visibility

Row-level filter applied to all read endpoints regardless of scope (see CONTEXT.md for the canonical statement):

- `published_public` — visible across all Organisations (anonymous included for public read paths)
- `published_org` — visible only within the author's Organisation
- `draft` — visible only to the author and their Organisation's Org Admins

## OpenAPI spec

A static export of the OpenAPI schema is committed at `openapi/openapi.json`. The schema is auto-published by CI on each release.

Regenerate the local copy after any route changes:

```bash
python3 -c "
from src.main import app
import json
with open('openapi/openapi.json', 'w') as f:
    json.dump(app.openapi(), f, indent=2)
"
```

## Middleware

| Middleware            | Purpose                                                                                                       |
| --------------------- | ------------------------------------------------------------------------------------------------------------- |
| `RequestIDMiddleware` | Echoes/generates `X-Request-ID` header; logs method, path, status, duration for request tracing and debugging |
| `RateLimitMiddleware` | Per-caller tiered rate limiting (anonymous / user / machine)                                                  |
| `CORSMiddleware`      | Configurable via `CORS_ORIGINS` env var                                                                       |

**Request tracing:** Include `X-Request-ID` in client requests, or one will be generated. All log entries and responses include this header for correlation across distributed systems.

## Caching

`GET /api/v1/prompts/featured`, `GET /api/v1/categories`, and `GET /api/v1/tags` are cached with a 60-second TTL. The cache is invalidated on any write to the affected resource. Set `REDIS_URL` to use Redis instead of the default in-process `cachetools.TTLCache`.

## Semantic search

`GET /api/v1/prompts?search=<query>` uses hybrid search: keyword ILIKE over title/description/prompt_text fused with vector cosine similarity via Reciprocal Rank Fusion (RRF). Prompts with a `NULL` embedding vector are still findable via the keyword half.

Embeddings are computed automatically on `POST /api/v1/prompts` (create) and on `PATCH /api/v1/prompts/{id}` when the embedding source text (title, description, or prompt_text) changes.

**Slim image / dev:** Set `EMBEDDING_USE_FAKE=true` to use the deterministic `FakeEmbedder` (no ML model needed). Search still works but rankings are random.

**Production image:** The published `app-with-embeddings` image bundles `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384-dim, multilingual). Override `EMBEDDING_MODEL` to use a different model — but note that switching models requires re-embedding all prompts (see below).

## Re-embedding prompts

Run `scripts/reembed.py` after switching `EMBEDDING_MODEL` or when first deploying on a database that already has prompts (to backfill missing vectors).

**When to run:**
- First deploy with embeddings on an existing database → `--only-missing`
- After changing `EMBEDDING_MODEL` → default (re-embeds everything)

The script is safe against a live database — it commits one batch at a time, holds no table locks, and is idempotent. If interrupted, re-run; at most one batch is reprocessed.

### Local / virtualenv

```bash
# Backfill only rows without a vector (first deploy):
python3 scripts/reembed.py --only-missing

# Re-embed everything (after model swap):
python3 scripts/reembed.py

# Preview without writing:
python3 scripts/reembed.py --dry-run

# Smaller batches (default: 100):
python3 scripts/reembed.py --batch-size 50
```

### Docker

The script runs inside the app container so it picks up the same `DATABASE_URL` and `EMBEDDING_MODEL` as the running service. Use `docker compose run` with `--no-deps` (infra is already up) and `--rm` to clean up the container afterward.

```bash
# Backfill missing vectors — typical first-deploy command:
docker compose --profile embeddings run --no-deps --rm app-embeddings \
  python3 scripts/reembed.py --only-missing

# Re-embed everything after switching EMBEDDING_MODEL:
docker compose --profile embeddings run --no-deps --rm app-embeddings \
  python3 scripts/reembed.py

# Dry-run to preview what would change:
docker compose --profile embeddings run --no-deps --rm app-embeddings \
  python3 scripts/reembed.py --dry-run
```

If you use the `full` or `simple` profile (slim image without bundled weights), set `EMBEDDING_MODEL` and ensure the model cache is mounted or `FASTEMBED_CACHE_PATH` points to a pre-populated directory:

```bash
docker compose run --no-deps --rm \
  -e EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
  -v /path/to/fastembed-cache:/root/.cache/fastembed \
  app python3 scripts/reembed.py --only-missing
```

## Migrations

```bash
alembic upgrade head          # apply all migrations
alembic revision --autogenerate -m "description"  # generate new migration
```
