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

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///data/gallery.db` | DB connection |
| `ENVIRONMENT` | `development` | `development` / `production` / `testing` |
| `JWT_SECRET_KEY` | `` | HMAC secret for dev/test (leave unset in prod) |
| `JWKS_URI` | `` | OIDC JWKS endpoint (prod) |
| `JWT_ISSUER` | `http://localhost:9000` | Expected `iss` claim |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins |

See `.env.example` for the full 17-variable list.

## Endpoints summary

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/v1/health` | None | Liveness + DB check |
| GET | `/api/v1/me` | Bearer | Current user profile |
| POST | `/api/v1/auth/generate-key` | `admin:manage_keys` | Generate machine JWT |
| GET | `/api/v1/prompts` | Optional | List/search prompts |
| GET | `/api/v1/prompts/featured` | Optional | Featured prompts |
| GET | `/api/v1/prompts/{id}` | Optional | Prompt detail |
| POST | `/api/v1/prompts` | `prompt:create` | Create prompt |
| PATCH | `/api/v1/prompts/{id}` | `prompt:write` | Update prompt |
| POST | `/api/v1/prompts/{id}/use` | None | Increment use count |
| POST | `/api/v1/prompts/{id}/rate` | `prompt:rate` | Submit rating |
| GET | `/api/v1/prompts/{id}/rate` | `prompt:rate` | Get own rating |
| GET | `/api/v1/prompts/{id}/ratings` | None | Rating stats |
| GET | `/api/v1/categories` | None | List categories |
| POST | `/api/v1/categories` | `admin:manage_taxonomy` | Create category |
| GET | `/api/v1/categories/{id}` | None | Category detail |
| PATCH | `/api/v1/categories/{id}` | `admin:manage_taxonomy` | Update category |
| DELETE | `/api/v1/categories/{id}` | `admin:manage_taxonomy` | Soft-delete category |
| GET | `/api/v1/tags` | None | List tags |
| POST | `/api/v1/tags` | `admin:manage_taxonomy` | Create tag |
| GET | `/api/v1/tags/{id}` | None | Tag detail |
| DELETE | `/api/v1/tags/{id}` | `admin:manage_taxonomy` | Soft-delete tag |

## Status transitions

Valid prompt status graph: `draft → published → archived → draft` (restore).  
Requires `prompt:publish` permission for any transition.

## Visibility

- `public` — visible to all (anonymous included)
- `internal` — requires authenticated caller
- `restricted` — requires `prompt:read:restricted` scope

## Migrations

```bash
alembic upgrade head          # apply all migrations
alembic revision --autogenerate -m "description"  # generate new migration
```
