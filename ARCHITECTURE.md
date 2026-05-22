# Architecture

## Overview

Prompt Gallery is a standalone FastAPI service. It is designed to be consumed by a learning platform (React SPA), an MCP-compatible chat client, and other API consumers.

```
┌──────────────────────┐
│  Management Platform  │   ← Identity Provider (future; issues JWTs + JWKS)
└──┬──────────────┬─────┘
   │ JWT bearer   │ JWT bearer
   ▼              ▼
┌──────────────┐  ┌──────────────┐
│ Learning     │  │  MCP/Chat    │
│ Platform     │  │  Clients     │
└──────┬───────┘  └──────────────┘
       │ HTTP /api/v1/prompts
       ▼
┌──────────────────────┐
│  Prompt Gallery API  │
│  FastAPI + Pydantic  │
│  SQLite / PostgreSQL │
└──────────────────────┘
```

## Layer structure

```
src/
├── main.py              # App factory, lifespan, CORS
├── config.py            # Pydantic Settings (env vars)
├── database.py          # Engine, SessionLocal, init_db()
├── dependencies.py      # DI: get_db, get_current_user, get_optional_user
│
├── middleware/
│   ├── auth.py          # Real JWT middleware: decode_and_verify, user upsert
│   │                    # AuthenticatedUser, get_current_user, get_optional_user
│   ├── request_id.py    # X-Request-ID echo/generate + request boundary logging
│   └── rate_limit.py    # Tiered rate limiting: anonymous/user/machine (in-memory counter)
│
├── models/              # SQLAlchemy 2.0 ORM models
│   ├── user.py          # Profile cache (auto-upserted from JWT claims)
│   ├── prompt.py        # Core entity
│   ├── category.py      # Pre-defined taxonomy (soft-deletable)
│   ├── tag.py           # Flexible tags (auto-created, soft-deletable)
│   ├── rating.py        # Unique per (prompt, user); 0–5
│   └── joins.py         # prompts_categories, prompts_tags (M2M)
│
├── schemas/             # Pydantic v2 request/response models
│   ├── common.py        # DataResponse[T], PaginatedResponse[T], envelopes
│   ├── prompt.py        # PromptCreate, PromptUpdate, PromptDetail, PromptSummary
│   ├── category.py      # CategoryCreate/Update/Detail
│   ├── tag.py           # TagCreate/Detail
│   ├── rating.py        # RatingSubmit/Detail/Stats
│   ├── user.py          # UserProfile (read-only)
│   └── upload.py        # UploadResponse
│
├── cache.py             # TTLCache (in-memory) or Redis; cache_get/set/delete/clear
│
├── routers/             # FastAPI APIRouter per domain
│   ├── health.py        # GET /health
│   ├── prompts.py       # /prompts CRUD, ratings, featured, use
│   ├── categories.py    # /categories CRUD
│   ├── tags.py          # /tags CRUD
│   ├── auth.py          # GET /me, POST /auth/generate-key
│   └── uploads.py       # POST/DELETE /uploads/images
│
├── embeddings/          # Semantic embedding layer
│   ├── base.py          # Embedder Protocol: embed_passage, embed_query, dimension
│   ├── fake.py          # FakeEmbedder: deterministic 384-dim unit vectors (dev/test)
│   ├── fastembed_embedder.py  # FastembedEmbedder: lazy-loaded real model via fastembed
│   └── __init__.py      # get_embedder() factory (EMBEDDING_USE_FAKE / EMBEDDING_MODEL)
│
├── storage/             # Pluggable file storage
│   ├── base.py          # StorageBackend Protocol
│   ├── local.py         # LocalFileSystemBackend (dev/test)
│   ├── s3.py            # S3Backend (production; requires boto3 + S3_* env vars)
│   └── __init__.py      # Factory: reads STORAGE_BACKEND env var
│
├── services/            # Business logic (no HTTP concerns)
│   ├── prompt_service.py    # CRUD, status transitions, ratings, featured
│   │                        # + embed on create/PATCH, hybrid search, vector cache
│   └── taxonomy_service.py  # Categories, tags, get_or_create_tags
│
└── utils/
    ├── jwt_utils.py     # decode_and_verify; JWTExpiredError, JWTInvalidError
    │                    # JWKS (5-min TTL cache) + HMAC dev fallback
    ├── response.py      # Envelope helper functions
    └── error.py         # AppError hierarchy, raise_http()

scripts/
├── generate_key.py      # CLI: generate machine JWT from JWT_SECRET_KEY
└── reembed.py           # CLI: re-embed all prompts (after model swap or first deploy)
```

## Key design decisions

| # | Decision | Rationale |
|---|---|---|
| Auth | Hybrid JWT: JWKS (prod RS256) + HMAC dev fallback (HS256, blocked in production) | One code path, two key sources |
| Storage | `StorageBackend` Protocol; `LocalFileSystemBackend` default, `S3Backend` optional | Swap backend via `STORAGE_BACKEND` env var without touching router code |
| Caching | `cachetools.TTLCache` (in-memory, 60 s) for featured/categories/tags; Redis when `REDIS_URL` set; invalidated on writes | Hot reads cached with zero infra requirement in dev |
| Rate limiting | `RateLimitMiddleware`: per-caller, per-minute window counter (anonymous/user/machine tiers) | Protects service without Redis/external dependency |
| Request tracing | `RequestIDMiddleware` echoes/generates `X-Request-ID`; logs method/path/status/duration per request | Every response traceable; structured log fields for prod aggregation |
| Token types | User tokens (short-lived) + machine tokens (long-lived, `POST /auth/generate-key`) | Covers interactive and service-to-service use |
| User upsert | `users` row upserted on every authenticated request from JWT claims | Profile always fresh; no separate sync job |
| Permissions | Flat `scope` list on `AuthenticatedUser`; `has_scope(perm)` check in routers | Matches JWT `scope` claim directly |
| Status transitions | `draft→published→archived→draft`; enforced in `_apply_status_transition` | Requires `prompt:publish` separate from `prompt:write` |
| Soft deletes | `deleted_at IS NULL` filter on all active queries; association rows are removed | Audit trail + recoverable |
| Tags | Auto-created on prompt create/update via `get_or_create_tags`; names lowercased | Flexible without admin overhead |
| Visibility | `public` / `internal` / `restricted`; unauthenticated callers see only `public+published` | Layered access without complex RBAC |
| Database | SQLite (dev/test), PostgreSQL (prod); `embedding_vector` stored as TEXT in SQLite | Alembic migration can add JSONB guard for Postgres |
| Semantic search | Hybrid: ILIKE keyword + brute-force cosine over in-process matrix cache; fused via RRF (k=60) | See ADR-0001; no pgvector needed at this corpus size |
| Embeddings | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384-dim) via `fastembed`; Protocol-based so model is swappable via `EMBEDDING_MODEL` | Dutch+English gallery content; multilingual model chosen per ADR-0002 |
| Vector cache | Module-level `dict[int, np.ndarray]` with 60s TTL; loaded lazily on first search; invalidated on same-process writes | Matches TTL pattern of featured/categories/tags cache |
| Embed on write | `create_prompt` always embeds; `update_prompt` re-embeds only when title/description/prompt_text changes | Avoid re-embedding on metadata-only PATCH (e.g., `featured`, `visibility`) |
| Response envelope | All responses wrapped: `{"data": ...}` or `{"data": ..., "meta": {...}}` | Consistent for all consumers |

## Auth flow

```
Request: Authorization: Bearer <token>
  ↓
middleware/auth.py: decode_and_verify(token)
  ├── JWKS_URI set?  → fetch JWKS (cached 5 min), verify RS256
  └── JWT_SECRET_KEY set + not production? → verify HS256 (dev only)
  ↓
Upsert users row (name, email, avatar_url, last_seen_at)
  ↓
AuthenticatedUser(id, external_id, name, email, scope, last_seen_at)
  ↓
Router dependency (get_current_user / get_optional_user)
```

Error mapping:
- `JWTExpiredError` → 401 `UNAUTHORIZED`
- `JWTInvalidError` → 401 `UNAUTHORIZED`
- Missing token on required endpoint → 401 `UNAUTHORIZED`
- Missing token on optional endpoint → anonymous (`None`)

## Data model

```
users ────────────────────────────────────── prompts
  id, external_id, name, email              id, title, description, prompt_text
  avatar_url, last_seen_at                  status, visibility, featured
                                            creator_id → users.id
                                            view_count, use_count
                                            created_at, updated_at, published_at
                                            deleted_at (soft delete)

prompts ←→ prompt_categories  (M2M via prompts_categories)
prompts ←→ prompt_tags        (M2M via prompts_tags)

prompt_ratings
  id, prompt_id, user_id, rating (0–5)
  UNIQUE (prompt_id, user_id)
```

## Embedding flow

```
POST /api/v1/prompts
  ↓
create_prompt (service)
  ├── embed_passage(title + "\n\n" + description + "\n\n" + prompt_text)
  │     embedder = get_embedder()  # FakeEmbedder in test/dev; FastembedEmbedder in prod
  ├── Store vector as JSON in embedding_vector column
  ├── Commit row (transactionally — embed failure blocks write)
  └── Invalidate in-process vector cache

PATCH /api/v1/prompts/{id}
  ↓
update_prompt (service)
  ├── Compute old_source / new_source from pre/post field state
  ├── If sources differ → re-embed (same transactional guarantee)
  └── If no change → skip re-embed, do NOT invalidate cache

GET /api/v1/prompts?search=<query>
  ↓
list_prompts (service)
  ├── Keyword path: ILIKE filter over (title, description, prompt_text)
  ├── Vector path: load matrix cache (60s TTL) → cosine sim → top-50
  ├── RRF fusion: score = Σ 1/(60 + rank) across both lists
  └── Paginate fused results; visibility filters applied before scoring
```

## Testing approach

- In-memory SQLite per test run (`scope="session"`)
- Per-test DB transaction rolled back after each test (isolation)
- `starlette.testclient.TestClient` for sync ASGI testing
- JWT fixtures: `make_jwt()` in `conftest.py` — HS256 signed with `JWT_SECRET_KEY="test-secret-key"`
- No mocks for DB — tests hit real service + DB layer
- JWKS endpoint mocked with `monkeypatch`/`unittest.mock` in `test_jwt_utils.py`
- Embeddings: `EMBEDDING_USE_FAKE=true` in conftest ensures `FakeEmbedder` is always used; vector cache reset between tests via `reset_vector_cache` autouse fixture
