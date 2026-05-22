# Prompt Gallery Extraction Plan

> **Status:** Draft — all 54 decisions resolved
> **Date:** 2025-05-01
> **Context:** Extract the prompt gallery from the learning platform into a standalone REST API service, designed to be consumed by the learning platform, a future MCP server, and other clients.

---

## Architecture Overview

```
┌──────────────────────┐
│  Management Platform   │   ← Identity Provider (auth, users, roles, tokens)
│  (not yet built)      │      Issues JWTs, manages JWKS
└──┬──────────────┬─────┘
   │              │
   │  JWT         │  JWT
   │  bearer      │  bearer
   ▼              ▼
┌──────────────┐  ┌───────────────┐
│ Learning     │  │ MCP-compatible  │
│ Platform     │  │ Chat Clients    │
│ (React SPA)  │  │                │
└──────┬───────┘  └───────────────┘
       │
       ▼  HTTP → /api/v1/prompts
┌───────────────────┐
│   Prompt Gallery   │   ← This service (standalone)
│   REST API         │
│   FastAPI + Pydantic│
│   PostgreSQL/SQLite│
└───────────────────┘
```

---

## Decision Log

### Identity & Authentication

| #   | Area               | Decision                                                                             | Rationale                                         |
| --- | ------------------ | ------------------------------------------------------------------------------------ | ------------------------------------------------- |
| 1a  | IdP                | Not yet built — design contract, stub it                                             | Future-proof, don't block development             |
| 1b  | Token mechanism    | Hybrid JWT: short-lived (users) + long-lived (machine/API key)                       | One auth path, covers all consumer types          |
| 1c  | Roles              | Permission claims in JWT (`scope`), no local roles                                   | Trust IdP, decouple from platform RBAC            |
| 1m  | Existing data      | Fresh start, no migration script                                                     | Extract is for a new service, not a data move     |
| 10a | Token delivery     | `Authorization: Bearer <jwt>` — header only                                          | Single pattern, no cookie complexity              |
| 10b | Profile upsert     | Auto-upsert `users` table on every auth'd request                                    | Guarantees freshness, negligible overhead         |
| 10c | JWT structure      | `sub`, `scope`, `name`, `email`, `avatar_url`, `iss`, `iat`, `exp` — no extra claims | Keep it simple; add `org_id` later if needed      |
| 11a | API keys           | Also JWT-signed (same mechanism)                                                     | One auth route, one validation path               |
| 11b | Header             | `Authorization: Bearer` (same as user)                                               | Single header convention                          |
| 11c | Key management     | API endpoint (`/api/v1/auth/generate-key`) + CLI script                              | API for runtime, CLI for bootstrap/dev            |
| 11d | Revocation         | TTL-bound user tokens + keypair rotation for machine keys                            | No deny list needed; bounded exposure window      |
| 5d  | JWT verification   | JWKS endpoint (prod) + shared secret HMAC (dev fallback)                             | Standard OIDC flow, simple dev mode               |
| 14  | Rate limiting      | Tiered: anonymous 30/min, user 120/min, machine 300/min                              | Protects against abuse, different client profiles |
| 14a | Rate limit backend | In-memory (dev), SQLite (prod) — no Redis for rate limiting. Redis is supported only as an optional caching layer (see decision 17). | Reuse existing DB for counters, no extra service  |

### Domain Model

| #   | Area                | Decision                                                                  | Rationale                                               |
| --- | ------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------- |
| 2a  | Users               | Minimal profile cache (auto-upsert from JWT)                              | Need `created_by`, rating dedup, audit trail            |
| 2b  | Platform references | Drop `linked_challenge_id` and `created_by_role` entirely                 | Meaningless outside platform                            |
| 2c  | Visibility          | `public` / `internal` / `restricted` (replaces `laag`/`gemiddeld`/`hoog`) | Generic vocabulary, not tied to Dutch municipal context |
| 2e  | Prompt review (AI)  | Drop entirely                                                             | Not core to gallery storage + retrieval                 |
| 2f  | Semantic search     | Keyword now, `embedding_vector` placeholder (JSONB, nullable)             | Add pipeline when needed, field is ready                |
| 2g  | Images              | Upload endpoints via gallery API                                          | Centralized, simple for current scale                   |

### Configuration

| #   | Area                  | Decision                                                              | Rationale                                                     |
| --- | --------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------- |
| 3a  | Image storage         | Pluggable adapter: LocalFileSystem (default) + S3 (optional)          | Cloud-agnostic, simple to swap                                |
| 3b  | Status values         | `draft` / `published` / `archived` (English)                          | Standard vocabulary for API consumers                         |
| 3c  | Pagination            | Offset-based (`page`, `per_page`)                                     | Simple, adequate for gallery scale                            |
| 3d  | API versioning        | `/api/v1/` path prefix                                                | Versioned from day one, easy to upgrade                       |
| 20  | Storage backends      | LocalFileSystem (always) + S3 (optional)                              | Local for dev/test, S3 for prod portability. Skip Cloudinary. |
| 21  | Schema naming         | Standard SQLAlchemy: plural table names, snake_case columns, `id` PKs | Conventional, readable                                        |
| 22  | Environment variables | 17 variables (see full list below)                                    | Documented defaults for all                                   |
| 18  | CORS                  | Whitelist origins (`CORS_ORIGINS` env var)                            | Explicit, secure                                              |

### Endpoint Design

| #     | Area                    | Decision                                                    | Rationale                                                   |
| ----- | ----------------------- | ----------------------------------------------------------- | ----------------------------------------------------------- |
| 4a    | Status transitions      | Embedded in PATCH body (`{status: "published"}`). Valid transitions: `draft→published`, `published→archived`, `archived→draft` (restore). All other transitions are rejected with `409 CONFLICT`. Requires `prompt:publish` permission; `prompt:write` alone is insufficient for status changes. | RESTful, single endpoint for all updates |
| 4b    | Ratings                 | Authenticated only (JWT required)                           | No anonymous ratings — prevents noise/spam                  |
| 4c    | Taxonomy                | Categories pre-defined; tags auto-create on prompt creation | Controlled taxonomy, flexible tags                          |
| 4d    | Image uploads           | Through gallery API (server handles storage call)           | Simple, no presigned URL complexity                         |
| 4e    | Deletion                | Soft-delete (archive) only, no hard-delete                  | Audit trail, recoverable                                    |
| 13b   | Category delete         | Soft-delete (remove from prompts, keep history)             | Consistent with soft-delete policy                          |
| 13d-a | Image max size          | 5MB                                                         | Prompt images rarely need large files                       |
| 13e   | Featured endpoint       | Respects caller permissions                                 | Authenticated callers see their accessible featured prompts |
| 13g   | User profile            | Read-only from JWT claims                                   | Profile managed by IdP, gallery just caches                 |
| 13h   | Category/tag assignment | Both inline (create/update) and separate endpoints          | Flexibility for full and incremental updates                |

### Authentication Permissions (Flat Claims)

| Permission               | Grants                                                        |
| ------------------------ | ------------------------------------------------------------- |
| `prompt:read`            | List, get detail, search, featured (public + internal)        |
| `prompt:read:restricted` | Access `restricted` visibility prompts                        |
| `prompt:create`          | Create new prompts                                            |
| `prompt:write`           | Update existing prompts (excluding status changes). Includes setting `featured: true/false`. |
| `prompt:publish`         | Transition status (draft→published, published→archived, etc.) |
| `prompt:rate`            | Submit or view own ratings                                    |
| `prompt:image`           | Upload/manage prompt images                                   |
| `admin:manage_taxonomy`  | CRUD on categories and tags                                   |
| `admin:manage_keys`      | Generate/revoke machine JWT keys                              |
| `admin:manage_users`     | View user profiles (admin console)                            |

**Typical role compositions (for IdP reference):**

```
viewer:   prompt:read
contributor: prompt:read prompt:create prompt:write prompt:rate prompt:image
publisher: + prompt:publish
admin:    + prompt:read:restricted admin:*
```

### API Specification

#### Prompts

| Method  | Path                           | Auth            | Description                                  |
| ------- | ------------------------------ | --------------- | -------------------------------------------- |
| `GET`   | `/api/v1/prompts`              | Bearer or None  | List/filter/search (paginated)               |
| `GET`   | `/api/v1/prompts/{id}`         | Bearer or None  | Detail (increments view_count)               |
| `POST`  | `/api/v1/prompts`              | `prompt:create` | Create (tags auto-created)                   |
| `PATCH` | `/api/v1/prompts/{id}`         | `prompt:write`  | Partial update (includes status transitions) |
| `POST`  | `/api/v1/prompts/{id}/rate`    | `prompt:rate`   | Submit/update rating (0-5)                   |
| `GET`   | `/api/v1/prompts/{id}/rate`    | `prompt:rate`   | Current user's rating                        |
| `GET`   | `/api/v1/prompts/{id}/ratings` | Bearer or None  | Aggregated stats (avg, count, distribution)  |
| `POST`  | `/api/v1/prompts/{id}/use`     | Bearer or None  | Increment use_count (call when a user copies/runs the prompt) |
| `GET`   | `/api/v1/prompts/featured`     | Bearer or None  | Featured prompts (respects permissions). **Must be registered before `/{id}` in the router to avoid path shadowing.** |

**Query params for `GET /prompts`:**

```
page, per_page          — pagination (default: page=1, per_page=20)
search                  — keyword (title, description, prompt_text)
status                  — draft, published, archived
visibility              — public, internal, restricted
featured                — true / false
category_id             — filter by category ID
tag                     — filter by tag name (repeatable)
sort                    — created_at, published_at, view_count, use_count, title
order                   — asc, desc (default: desc)
```

#### Categories

| Method   | Path                      | Auth                    | Description                    |
| -------- | ------------------------- | ----------------------- | ------------------------------ |
| `GET`    | `/api/v1/categories`      | None                    | List all categories            |
| `POST`   | `/api/v1/categories`      | `admin:manage_taxonomy` | Create category                |
| `GET`    | `/api/v1/categories/{id}` | None                    | Category detail + prompt count |
| `PATCH`  | `/api/v1/categories/{id}` | `admin:manage_taxonomy` | Update category                |
| `DELETE` | `/api/v1/categories/{id}` | `admin:manage_taxonomy` | Soft-delete (untag prompts)    |

#### Tags

| Method   | Path                | Auth                    | Description                 |
| -------- | ------------------- | ----------------------- | --------------------------- |
| `GET`    | `/api/v1/tags`      | None                    | List all tags               |
| `POST`   | `/api/v1/tags`      | `admin:manage_taxonomy` | Create/merge tag            |
| `GET`    | `/api/v1/tags/{id}` | None                    | Tag detail + prompt count   |
| `DELETE` | `/api/v1/tags/{id}` | `admin:manage_taxonomy` | Soft-delete (untag prompts) |

> Tag names are immutable after creation. To rename, soft-delete the old tag and create a new one.

#### Image Uploads

| Method   | Path                           | Auth           | Body                  | Description                 |
| -------- | ------------------------------ | -------------- | --------------------- | --------------------------- |
| `POST`   | `/api/v1/uploads/images`       | `prompt:image` | `multipart/form-data` | Upload image → `{url, key}` |
| `DELETE` | `/api/v1/uploads/images/{key}` | `prompt:image` | —                     | Delete image (204)          |

#### Authentication

| Method | Path                        | Auth                | Description                      |
| ------ | --------------------------- | ------------------- | -------------------------------- |
| `GET`  | `/api/v1/me`                | Bearer (user JWT)   | Current user profile (read-only) |
| `POST` | `/api/v1/auth/generate-key` | `admin:manage_keys` | Generate machine JWT             |

#### Infrastructure

| Method | Path             | Auth | Description                                |
| ------ | ---------------- | ---- | ------------------------------------------ |
| `GET`  | `/api/v1/health` | None | Liveness check (DB connectivity + version) |

#### Response Format (Standard Envelope)

```json
// Success (paginated list)
{
  "data": [{...}, {...}],
  "meta": {
    "total": 42,
    "page": 1,
    "per_page": 20,
    "pages": 3
  }
}

// Success (single resource)
{
  "data": {...}
}

// Success (create/update)
{
  "data": {...},
  "meta": {"action": "created"}
}

// Error
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Prompt with ID 5 does not exist"
  }
}
```

**Error codes:**

| HTTP Status | Code                  | Meaning                            |
| ----------- | --------------------- | ---------------------------------- |
| 400         | `VALIDATION_ERROR`    | Request body invalid               |
| 401         | `UNAUTHORIZED`        | Missing or invalid auth token      |
| 403         | `FORBIDDEN`           | Authenticated but lacks permission |
| 404         | `NOT_FOUND`           | Resource does not exist            |
| 409         | `CONFLICT`            | Business rule violation            |
| 413         | `PAYLOAD_TOO_LARGE`   | Upload exceeds max size            |
| 429         | `RATE_LIMITED`        | Too many requests                  |
| 500         | `INTERNAL_ERROR`      | Internal server error              |
| 503         | `SERVICE_UNAVAILABLE` | Backend unavailable                |

### Data Model

```sql
-- Users (profile cache, auto-upserted from JWT claims)
CREATE TABLE users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id  TEXT    NOT NULL UNIQUE,      -- JWT "sub" claim
    name         TEXT,
    email        TEXT,
    avatar_url   TEXT,
    last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Prompts
CREATE TABLE prompts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    title             TEXT    NOT NULL,         -- indexed
    description       TEXT    NOT NULL,
    prompt_text       TEXT    NOT NULL,
    example_output    TEXT,
    image_url         TEXT,
    status            TEXT    NOT NULL DEFAULT 'draft',     -- draft, published, archived
    visibility        TEXT    NOT NULL DEFAULT 'public',    -- public, internal, restricted
    featured          BOOLEAN NOT NULL DEFAULT FALSE,
    creator_id        INTEGER NOT NULL REFERENCES users(id),
    embedding_vector  TEXT,                      -- stored as JSON string; Alembic overrides to JSONB on PostgreSQL. Placeholder for future semantic search.
    view_count        INTEGER NOT NULL DEFAULT 0,
    use_count         INTEGER NOT NULL DEFAULT 0,   -- incremented via POST /api/v1/prompts/{id}/use
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at      TIMESTAMP,
    deleted_at        TIMESTAMP                                  -- NULL = active; non-NULL = soft-deleted (status set to 'archived')
);

-- Categories
CREATE TABLE prompt_categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,        -- indexed
    description TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at  TIMESTAMP                       -- NULL = active; non-NULL = soft-deleted
);

-- Tags
CREATE TABLE prompt_tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,        -- indexed
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at  TIMESTAMP                       -- NULL = active; non-NULL = soft-deleted
);

-- Association tables
CREATE TABLE prompts_categories (
    prompt_id      INTEGER NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
    category_id    INTEGER NOT NULL REFERENCES prompt_categories(id) ON DELETE CASCADE,
    PRIMARY KEY (prompt_id, category_id)
);

CREATE TABLE prompts_tags (
    prompt_id      INTEGER NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
    tag_id         INTEGER NOT NULL REFERENCES prompt_tags(id) ON DELETE CASCADE,
    PRIMARY KEY (prompt_id, tag_id)
);

-- Ratings
CREATE TABLE prompt_ratings (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
    user_id   INTEGER NOT NULL REFERENCES users(id),
    rating    INTEGER NOT NULL CHECK(rating >= 0 AND rating <= 5),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (prompt_id, user_id)
);
```

### Environment Variables

| Variable               | Required   | Default                     | Purpose                                          |
| ---------------------- | ---------- | --------------------------- | ------------------------------------------------ |
| `DATABASE_URL`         | Yes        | `sqlite:///data/gallery.db` | Database connection string                       |
| `JWKS_URI`             | Yes (prod) | —                           | JWKS endpoint URL for JWT verification           |
| `JWT_ISSUER`           | Yes (prod) | `http://localhost:9000`     | Expected `iss` claim value                       |
| `JWT_SECRET_KEY`       | Dev only   | —                           | Shared HMAC secret for JWT dev fallback. Set when `JWKS_URI` is absent. Do not use in production. |
| `STORAGE_BACKEND`      | No         | `local`                     | `local` or `s3`                                  |
| `STORAGE_LOCAL_PATH`   | No         | `./uploads`                 | Local file storage directory                     |
| `S3_BUCKET`            | S3 only    | —                           | S3 bucket name                                   |
| `S3_REGION`            | S3 only    | `eu-west-1`                 | AWS region                                       |
| `S3_ACCESS_KEY`        | S3 only    | —                           | AWS access key ID                                |
| `S3_SECRET_KEY`        | S3 only    | —                           | AWS secret access key                            |
| `CORS_ORIGINS`         | No         | `http://localhost:5173`     | Comma-separated allowed CORS origins             |
| `REDIS_URL`            | No         | —                           | Redis URL for optional caching layer (`cachetools.TTLCache` used otherwise). Not used for rate limiting. |
| `LOG_LEVEL`            | No         | `info`                      | `debug`, `info`, `warning`, `error`              |
| `ENVIRONMENT`          | No         | `development`               | `development`, `production`, `testing`           |
| `RATE_LIMIT_ANONYMOUS` | No         | `30`                        | Requests/min for anonymous callers               |
| `RATE_LIMIT_USER`      | No         | `120`                       | Requests/min for authenticated users             |
| `RATE_LIMIT_MACHINE`   | No         | `300`                       | Requests/min for machine tokens                  |
| `MAX_UPLOAD_SIZE`      | No         | `5242880`                   | Max file upload size in bytes (5MB)              |

### Technology Stack

| Layer         | Choice                                                           | Rationale                                                                      |
| ------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Framework     | **FastAPI**                                                      | Async-native, OpenAPI auto-gen, Pydantic schemas, smaller dependency footprint |
| Location      | **Separate repo** `prompt-gallery/`                              | Independent CI/CD, versioning, deployment                                      |
| Database      | **PostgreSQL** (prod) / **SQLite** (dev)                         | Production-grade, JSONB support, pgvector-ready. Alembic migration uses `op.execute()` with `IF` guards or dialect checks to apply PostgreSQL-specific types (`JSONB`, full-text indexes) only when the target DB is PostgreSQL. SQLite uses `TEXT` for those columns. |
| ORM           | **SQLAlchemy 2.0**                                               | Familiar, migrations via Alembic, proven                                       |
| Schemas       | **Pydantic v2**                                                  | Native to FastAPI, replaces Marshmallow                                        |
| Server        | **Uvicorn**                                                      | Async-native, matches FastAPI                                                  |
| Testing       | **pytest** + `httpx.AsyncClient`                                 | Standard FastAPI test pattern, in-memory SQLite                                |
| Migrations    | **Alembic**                                                      | Matches SQLAlchemy ecosystem                                                   |
| Logging       | **JSON** (prod) / **text** (dev)                                 | Machine-parsable for pipelines, readable for dev                               |
| Auth          | **JWT via JWKS** + HMAC dev fallback                             | Standard OIDC, configurable for dev                                            |
| Search        | **SQL LIKE** (dev) / **PostgreSQL full-text** (prod)             | Hybrid, no extra service needed                                                |
| Rate limiting | **Tiered, DB-backed**                                            | SQLite for counters, configurable limits per caller type                       |
| Caching       | **In-memory** default, **Redis** when configured                 | `cachetools.TTLCache` for hot reads                                            |
| Storage       | **Pluggable adapter** (Local + S3)                               | LocalFileSystem default, S3 optional                                           |
| OpenAPI docs  | **Swagger** (`/docs`) + **ReDoc** (`/redoc`) + **static export** | Interactive for dev, static for consumers                                      |
| CLI           | **Python script** (`scripts/generate_key.py`)                    | Bootstrap dev keys without API access                                          |

### Project Structure

```
prompt-gallery/
├── src/
│   ├── __init__.py
│   ├── main.py                   # FastAPI app factory, lifespan
│   ├── config.py                 # Pydantic Settings (env vars)
│   ├── dependencies.py           # FastAPI DI (auth, DB session)
│   │
│   ├── models/
│   │   ├── __init__.py           # Import all models, declarative base
│   │   ├── user.py               # Users (profile cache)
│   │   ├── prompt.py             # Prompts
│   │   ├── category.py           # PromptCategory
│   │   ├── tag.py                # PromptTag
│   │   ├── rating.py             # PromptRating
│   │   └── joins.py              # M2M association tables
│   │
│   ├── schemas/                  # Pydantic v2 request/response models
│   │   ├── __init__.py
│   │   ├── common.py             # Envelope, pagination, error schemas
│   │   ├── user.py
│   │   ├── prompt.py
│   │   ├── category.py
│   │   ├── tag.py
│   │   ├── rating.py
│   │   └── upload.py
│   │
│   ├── routers/                  # FastAPI APIRouter per domain
│   │   ├── __init__.py
│   │   ├── prompts.py            # /prompts CRUD, search, rate, featured
│   │   ├── categories.py         # /categories CRUD
│   │   ├── tags.py               # /tags CRUD
│   │   ├── uploads.py            # /uploads/images (upload + delete)
│   │   ├── auth.py               # /me (profile), /auth/generate-key
│   │   └── health.py             # /health
│   │
│   ├── services/                 # Business logic
│   │   ├── __init__.py
│   │   ├── prompt_service.py     # CRUD, status transitions, ratings
│   │   ├── taxonomy_service.py   # Categories + tags (incl. auto-create)
│   │   ├── search_service.py     # Search backend abstraction
│   │   └── storage_service.py    # Storage adapter factory
│   │
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── auth.py               # JWT validation, scope → permission extraction
│   │   ├── rate_limit.py         # Tiered rate limiting
│   │   └── request_id.py         # X-Request-ID trace propagation
│   │
│   ├── storage/                  # Pluggable storage backends
│   │   ├── __init__.py           # Factory (env-based selection)
│   │   ├── base.py               # StorageBackend Protocol
│   │   ├── local.py              # LocalFileSystem implementation
│   │   └── s3.py                 # S3 implementation (optional)
│   │
│   └── utils/
│       ├── response.py           # Envelope formatter helpers
│       ├── error.py              # Custom exceptions, error → HTTP mapper
│       └── jwt_utils.py          # JWKS fetch + cache, HMAC dev fallback
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Fixtures: app, client, DB, sample data, JWTs
│   ├── test_auth.py
│   ├── test_prompts.py
│   ├── test_categories.py
│   ├── test_tags.py
│   ├── test_ratings.py
│   ├── test_uploads.py
│   ├── test_rate_limit.py
│   ├── test_health.py
│   └── test_openapi.py          # Validate generated OpenAPI spec
│
├── migrations/                   # Alembic
│   ├── env.py
│   └── versions/
│
├── scripts/
│   └── generate_key.py           # CLI: generate machine JWT keys
│
├── openapi/                      # Generated OpenAPI spec (static export)
│   └── openapi.json
│
├── pyproject.toml               # Project metadata, build config
├── requirements.txt              # Runtime dependencies
├── requirements-dev.txt          # Dev + test dependencies
└── README.md
```

### Storage Adapter Interface

```python
# src/storage/base.py
class StorageBackend(Protocol):
    async def upload(self, file: bytes, filename: str, content_type: str) -> dict:
        """Upload file. Returns {"url": "...", "key": "..."}. """
        ...

    async def get_url(self, file_key: str) -> str:
        """Get public URL for existing file."""
        ...

    async def delete(self, file_key: str) -> None:
        """Delete file from storage."""
        ...
```

### OpenAPI Spec Export

```bash
# During build or on demand
python -c "
from src.main import app
import json
with open('openapi/openapi.json', 'w') as f:
    json.dump(app.openapi(), f, indent=2)
"
```

### Observability

- **Structured JSON logging** in production (all log lines include `request_id`, `method`, `path`, `duration_ms`, `status_code`)
- **`X-Request-ID`** header: accept from caller, generate if missing, propagate in response
- **Health endpoint** (`/api/v1/health`): checks DB connectivity, returns `{status: "ok", version: "0.1.0"}`

### Future Considerations (Not in Scope)

| Feature               | Notes                                                                                                                 |
| --------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **Semantic search**   | `embedding_vector` column is ready. Add embedding pipeline + vector search when needed (pgvector or in-memory FAISS). |
| **Multi-tenancy**     | Schema has no `org_id`. Add when multi-tenant need arises (affects all tables and queries).                           |
| **Webhooks / events** | Not needed now. Platform can poll. Add event bus layer when needed.                                                   |
| **TypeScript client** | Can be auto-generated from OpenAPI spec when a consumer needs it.                                                     |
| **MCP server**        | Can be built on top of this REST API as a thin translation layer (current `prompt_gallery_mcp.py` pattern).           |
| **Redis**             | Available for caching and rate limiting. Configured via `REDIS_URL`.                                                  |

### Extraction Impact on Existing Platform

Files in the learning platform that reference prompts and need to be updated after extraction:

| File                                              | Impact                         | Action                                                    |
| ------------------------------------------------- | ------------------------------ | --------------------------------------------------------- |
| `backend/app/models/prompt.py`                    | 4 models removed               | Delete + remove from `models/__init__.py`                 |
| `backend/app/models/user.py`                      | `created_prompts` relationship | Remove FK reference                                       |
| `backend/app/routes/prompts.py`                   | Full blueprint removed         | Delete file + `app/__init__.py`                           |
| `backend/app/routes/prompt_review.py`             | AI review removed              | Delete file + `app/__init__.py`                           |
| `backend/app/routes/public.py`                    | `total_prompts` count          | Replace with HTTP call to gallery `/health` stats or drop |
| `backend/app/services/prompt_service.py`          | Business logic moved           | Delete file                                               |
| `backend/app/services/prompt_review_service.py`   | Deleted                        | Delete file                                               |
| `backend/app/repositories/prompt_repository.py`   | Moved to gallery               | Delete file                                               |
| `backend/app/schemas/prompt_schema.py`            | Moved to gallery (Pydantic)    | Delete file                                               |
| `backend/app/services/dashboard_service.py`       | Prompt stats query             | Replace with HTTP call to gallery API                     |
| `backend/app/models/user_dashboard_preference.py` | "prompts" widget config        | No change needed — just cosmetic label                    |
| `frontend/src/services/promptService.js`          | API base URL                   | Update to point to gallery URL                            |
| `backend/app/models/submission.py` / `.py`        | `block_type: "prompt"`         | No change — unrelated string label                        |

### Implementation Phases

#### Phase 1: Skeleton

- Project structure, `pyproject.toml`, `requirements.txt`
- SQLAlchemy models (7 files)
- Alembic initial migration
- Config (`config.py` with all 17 env vars)
- `main.py` with lifespan, router registration
- `/health` endpoint
- `.env.example` with all env vars + `.gitignore` for Python artifacts
> **Decision**: No Dockerfile or docker-compose. This workspace already runs inside Docker; local install via `pip install -e .` and `uvicorn src.main:app` avoids Docker-in-Docker pitfalls. Production containerization belongs in the CI/CD pipeline.
- Basic tests (conftest, health check)

#### Phase 2: Auth & Middleware

- JWKS fetcher + JWT validation (`jwt_utils.py`)
- Auth middleware (`middleware/auth.py`)
- User auto-upsert
- `/me` endpoint
- `/auth/generate-key` endpoint
- CLI key generation script
- Test fixtures for signed JWTs

#### Phase 3: Core API — Prompts

- Pydantic schemas (prompt, category, tag, rating, upload)
- Prompt CRUD routers (`routers/prompts.py`)
- Business logic (`services/prompt_service.py`)
- Taxonomy service with auto-create
- Category + tag routers
- Standard envelope responses
- Search backend (keyword)
- Full test suite

> **Note on schema timing:** Pydantic schemas are intentionally deferred to Phase 3. Phase 1 and 2 endpoints (`/health`, `/me`, `/auth/generate-key`) use inline response dicts or minimal ad-hoc models. The shared `schemas/` layer is built once here, covering all domain types together before any CRUD endpoint is wired up.

#### Phase 4: Image Uploads

- Storage adapter framework (`storage/base.py`, `local.py`)
- Upload router + multipart handling
- S3 adapter (optional)
- File size validation
- Delete endpoint
- **Test strategy:** `LocalFileSystem` tests use pytest's `tmp_path` fixture (real FS, auto-cleaned). S3 adapter tests mock `boto3` via `moto`. Both adapters are exercised through the API client in `tests/test_uploads.py`, not called directly.

#### Phase 5: Polish

- Rate limiting middleware
- Caching (in-memory for featured, categories, tags)
- JSON logging + `X-Request-ID`
- CORS configuration
- OpenAPI static export
- Documentation (README)

---

## Summary — All 54 Decisions

| #     | Area                | Decision                                                           |
| ----- | ------------------- | ------------------------------------------------------------------ |
| 1a    | IdP                 | Not yet built — design contract only                               |
| 1b    | Tokens              | Hybrid JWT (short-lived user, long-lived machine)                  |
| 1c    | Roles               | Flat permission claims in JWT, no local roles                      |
| 1m    | Data                | Fresh start, no migration                                          |
| 2a    | Users               | Minimal profile cache, auto-upsert from JWT                        |
| 2b    | Platform refs       | Drop entirely                                                      |
| 2c    | Visibility          | `public` / `internal` / `restricted`                               |
| 2e    | Prompt review       | Drop entirely                                                      |
| 2f    | Semantic search     | Keyword now, `embedding_vector` placeholder                        |
| 2g    | Images              | Upload via gallery API                                             |
| 3a    | Image storage       | Pluggable: LocalFileSystem + S3                                    |
| 3b    | Status              | English: `draft` / `published` / `archived`                        |
| 3c    | Pagination          | Offset-based                                                       |
| 3d    | API versioning      | `/api/v1/` prefix                                                  |
| 4a    | Status transitions  | Embedded in PATCH body                                             |
| 4b    | Ratings             | Authenticated only                                                 |
| 4c    | Taxonomy            | Categories pre-defined, tags auto-create                           |
| 4d    | Image upload        | Through gallery API                                                |
| 4e    | Deletion            | Soft-delete only                                                   |
| 5a    | Permission claims   | Flat list in `scope`                                               |
| 5b    | Permission set      | 10 permissions defined, complete                                   |
| 5c    | API keys            | JWT-based (same mechanism)                                         |
| 5d    | JWT verification    | JWKS + HMAC dev fallback                                           |
| 8     | Response format     | Standard `data`/`meta`/`error` envelope                            |
| 8a    | Error codes         | HTTP status + domain-specific code                                 |
| 9     | Frontend            | Platform frontend calls gallery API via CORS                       |
| 9a    | Language            | API in English, content in Dutch. All field names, error codes, and status values are English. Prompt text, titles, and descriptions may be in Dutch — the API treats them as opaque strings. |
| 10a   | Token delivery      | `Authorization: Bearer` header only                                |
| 10b   | Profile upsert      | Every authenticated request                                        |
| 10c   | JWT structure       | `sub`, `scope`, `name`, `email`, `avatar_url`, `iss`, `iat`, `exp` |
| 11a   | API keys            | JWT-signed (unified auth path)                                     |
| 11b   | Auth header         | `Authorization: Bearer` (same as users)                            |
| 11c   | Key management      | API endpoint + CLI script                                          |
| 11d   | Revocation          | TTL-bound + keypair rotation                                       |
| 13    | API spec            | Complete endpoint list documented                                  |
| 13b   | Category delete     | Soft-delete                                                        |
| 13d-a | Image max size      | 5MB                                                                |
| 13e   | Featured            | Respects caller permissions                                        |
| 13g   | Profile             | Read-only from JWT claims                                          |
| 13h   | Taxonomy assignment | Both inline and separate                                           |
| 14    | Rate limiting       | Tiered: 30/120/300 per minute                                      |
| 14a   | Rate limit backend  | In-memory dev, SQLite prod                                         |
| 15    | Search              | Hybrid LIKE + PostgreSQL full-text                                 |
| 16    | Logging             | JSON prod, text dev                                                |
| 16a   | Request tracing     | `X-Request-ID` propagate                                           |
| 17    | Caching             | In-memory default, Redis optional                                  |
| 18    | CORS                | Whitelist origins                                                  |
| 19    | OpenAPI docs        | Interactive + static export                                        |
| 19a   | TS client           | Defer                                                              |
| 20    | Storage backends    | Local (always) + S3 (optional)                                     |
| 21    | Schema naming       | Standard SQLAlchemy conventions                                    |
| 22    | Env vars            | 17 variables, all documented                                       |
| 23    | Project structure   | As documented (src/ tree)                                          |
| 24    | Server              | Uvicorn (async-native)                                             |
| 25    | Testing             | pytest + httpx, in-memory SQLite                                   |
| 26    | CLI                 | Python script                                                      |
