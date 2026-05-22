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

There are two additional docker compose profiles:

For hot-reloading dev-setup:

```
docker-compose up --profile dev
```

If you just want to run the prompt gallery:

```
docker-compose up --profile simple
```

Build and run the image directly:

```bash
docker build -t prompt-gallery .
docker run -p 8000:8000 prompt-gallery
```

The image is automatically published on each release. See GitHub Actions workflow for registry details.

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

## Migrations

```bash
alembic upgrade head          # apply all migrations
alembic revision --autogenerate -m "description"  # generate new migration
```
