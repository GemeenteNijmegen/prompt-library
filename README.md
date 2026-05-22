# Prompt Gallery API

Standalone REST API for managing, searching, and rating AI prompts. Built with FastAPI + SQLAlchemy + Pydantic v2.

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

There are three additional docker compose profiles:

For hot-reloading dev-setup:

```
docker-compose up --profile dev
```

If you just want to run the prompt gallery:

```
docker-compose up --profile simple
```

For real semantic search with the bundled ML model (requires building `app-with-embeddings`):

```
docker-compose --profile embeddings up
```

This starts Postgres, Redis, and the `app-with-embeddings` image which has `intfloat/multilingual-e5-small` weights pre-baked in. The default (`full`) profile uses the slim image with `EMBEDDING_USE_FAKE=false` (fastembed downloads on first use if model is not cached).

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

## Authentication

All protected endpoints use `Authorization: Bearer <jwt>`.

**Dev / testing mode (HMAC):** Set `JWT_SECRET_KEY` in `.env` and leave `JWKS_URI` empty. Tokens are HS256-signed with the shared secret.

**Production mode (JWKS):** Set `JWKS_URI` to your identity provider's JWKS endpoint. Tokens must be RS256-signed.

Generate a dev machine token:

```bash
JWT_SECRET_KEY=my-secret python3 scripts/generate_key.py \
  --scope prompt:read prompt:create \
  --expires-in-days 365
```

## API prefix

All routes are under `/api/v1/`. Health: `GET /api/v1/health`.

## Environment variables

| Variable               | Default                     | Purpose                                                            |
| ---------------------- | --------------------------- | ------------------------------------------------------------------ |
| `DATABASE_URL`         | `sqlite:///data/gallery.db` | DB connection                                                      |
| `ENVIRONMENT`          | `development`               | `development` / `production` / `testing`                           |
| `JWT_SECRET_KEY`       | ``                          | HMAC secret for dev/test (leave unset in prod)                     |
| `JWKS_URI`             | ``                          | OIDC JWKS endpoint (prod)                                          |
| `JWT_ISSUER`           | `http://localhost:9000`     | Expected `iss` claim                                               |
| `CORS_ORIGINS`         | `http://localhost:5173`     | Comma-separated allowed origins                                    |
| `STORAGE_BACKEND`      | `local`                     | `local` or `s3`                                                    |
| `STORAGE_LOCAL_PATH`   | `./uploads`                 | Local file upload directory                                        |
| `S3_BUCKET`            | ``                          | S3 bucket name (when `STORAGE_BACKEND=s3`)                         |
| `S3_REGION`            | `eu-west-1`                 | AWS region                                                         |
| `S3_ACCESS_KEY`        | ``                          | AWS access key                                                     |
| `S3_SECRET_KEY`        | ``                          | AWS secret key                                                     |
| `REDIS_URL`            | ``                          | Redis URL for caching (optional; uses in-memory TTLCache if unset) |
| `RATE_LIMIT_ANONYMOUS` | `30`                        | Requests/min for unauthenticated callers                           |
| `RATE_LIMIT_USER`      | `120`                       | Requests/min for authenticated users                               |
| `RATE_LIMIT_MACHINE`   | `300`                       | Requests/min for machine tokens                                    |
| `MAX_UPLOAD_SIZE`      | `5242880`                   | Max upload file size in bytes (default: 5 MB)                      |
| `LOG_LEVEL`            | `info`                      | Log verbosity: `debug`, `info`, `warning`, `error`                 |
| `EMBEDDING_MODEL`      | `intfloat/multilingual-e5-small` | Sentence embedding model for semantic search                  |
| `EMBEDDING_USE_FAKE`   | `false`                     | Use deterministic fake embedder (for dev/test; always set in CI)   |

See `.env.example` for the full variable list.

## Endpoints summary

| Method | Path                           | Auth                    | Description                           |
| ------ | ------------------------------ | ----------------------- | ------------------------------------- |
| GET    | `/api/v1/health`               | None                    | Liveness + DB check                   |
| GET    | `/api/v1/me`                   | Bearer                  | Current user profile                  |
| POST   | `/api/v1/auth/generate-key`    | `admin:manage_keys`     | Generate machine JWT                  |
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

Valid prompt status graph: `draft → published → archived → draft` (restore).  
Requires `prompt:publish` permission for any transition.

## Visibility

- `public` — visible to all (anonymous included)
- `internal` — requires authenticated caller
- `restricted` — requires `prompt:read:restricted` scope

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

**Production image:** The published `app-with-embeddings` image bundles `intfloat/multilingual-e5-small` (384-dim, multilingual). Override `EMBEDDING_MODEL` to use a different model — but note that switching models requires re-embedding all prompts (see below).

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
  -e EMBEDDING_MODEL=intfloat/multilingual-e5-small \
  -v /path/to/fastembed-cache:/root/.cache/fastembed \
  app python3 scripts/reembed.py --only-missing
```

## Migrations

```bash
alembic upgrade head          # apply all migrations
alembic revision --autogenerate -m "description"  # generate new migration
```
