# Architecture

## Overview

Prompt Gallery is a standalone FastAPI service. It is designed to be consumed by a learning platform (React SPA), an MCP-compatible chat client, and other API consumers.

```
┌──────────────────────┐
│  Management Platform  │   ← Identity Provider (future; issues JWTs)
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
├── config.py            # Pydantic Settings (17 env vars)
├── database.py          # Engine, SessionLocal, init_db()
├── dependencies.py      # DI: get_db, get_current_user, get_optional_user
├── auth_stub.py         # Dev-mode stub auth (replaced wholesale in Phase 3)
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
├── routers/             # FastAPI APIRouter per domain
│   ├── health.py        # GET /health
│   ├── prompts.py       # /prompts CRUD, ratings, featured, use
│   ├── categories.py    # /categories CRUD
│   ├── tags.py          # /tags CRUD
│   └── auth.py          # GET /me
│
├── services/            # Business logic (no HTTP concerns)
│   ├── prompt_service.py    # CRUD, status transitions, ratings, featured
│   └── taxonomy_service.py  # Categories, tags, get_or_create_tags
│
└── utils/
    ├── response.py      # Envelope helper functions
    └── error.py         # AppError hierarchy, raise_http()
```

## Key design decisions

| # | Decision | Rationale |
|---|---|---|
| Auth | Stub JWT in dev (`DEV_STUB_TOKEN`); `dependencies.py` is the single swap point for real JWKS auth | One line change for Phase 3 |
| Permissions | Flat `scope` list on user object; `has_scope(perm)` check in routers | Matches JWT `scope` claim |
| Status transitions | `draft→published→archived→draft`; enforced in `_apply_status_transition` | Requires `prompt:publish` separate from `prompt:write` |
| Soft deletes | `deleted_at IS NULL` filter on all active queries; association rows are removed | Audit trail + recoverable |
| Tags | Auto-created on prompt create/update via `get_or_create_tags`; names lowercased | Flexible without admin overhead |
| Visibility | `public` / `internal` / `restricted`; unauthenticated callers see only `public+published` | Layered access without complex RBAC |
| Database | SQLite (dev/test), PostgreSQL (prod); `embedding_vector` stored as TEXT in SQLite | Alembic migration can add JSONB guard for Postgres |
| Response envelope | All responses wrapped: `{"data": ...}` or `{"data": ..., "meta": {...}}` | Consistent for all consumers |

## Auth flow (Phase 2 stub)

```
Request with "Authorization: Bearer <token>"
  → auth_stub.py: matches DEV_STUB_TOKEN?
    Yes → StubUser with all scopes
    No  → 401 UNAUTHORIZED
```

Phase 3 will replace `auth_stub.py` with real JWKS-based validation. Only the import in `dependencies.py` needs updating.

## Data model

```
users ────────────────────────────────────── prompts
  id, external_id, name, email              id, title, description, prompt_text
                                            status, visibility, featured
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

## Testing approach

- In-memory SQLite per test run (`scope="session"`)
- Per-test DB transaction rolled back after each test (isolation)
- `starlette.testclient.TestClient` for sync ASGI testing
- Fixtures: `dev_user`, `sample_prompt`, `sample_category`, `sample_tag`
- No mocks — tests hit real service + DB layer
