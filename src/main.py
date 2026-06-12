import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from src.config import settings
from src.database import init_db
from src.middleware.rate_limit import RateLimitMiddleware
from src.middleware.request_id import RequestIDMiddleware
from src.routers import health, categories, tags, prompts, me, uploads, admin
from src.utils.openapi_responses import OPTIONAL_AUTH_MARKER

logging.basicConfig(
    level=settings.LOG_LEVEL.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logging.getLogger("sqlalchemy").propagate = False
logger = logging.getLogger(__name__)


def _install_openapi(app: FastAPI) -> None:
    """Wrap ``app.openapi`` to express optional authentication.

    Routes that accept but do not require a token are tagged with
    ``OPTIONAL_AUTH_MARKER`` via ``openapi_extra``. FastAPI would otherwise
    render them as requiring a bearer token (identical to mandatory-auth
    routes), so here we rewrite their security to ``[{}, {"HTTPBearer": []}]`` —
    the empty object signalling that anonymous access is allowed.
    """

    def openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
        )
        for path_item in schema.get("paths", {}).values():
            for operation in path_item.values():
                if isinstance(operation, dict) and operation.pop(OPTIONAL_AUTH_MARKER, None):
                    operation["security"] = [{}, {"HTTPBearer": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = openapi


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — environment=%s", settings.ENVIRONMENT)
    init_db()
    yield
    logger.info("Shutting down")


def create_app(
    rate_limit_anonymous: int | None = None,
    rate_limit_user: int | None = None,
    rate_limit_azp: int | None = None,
    rate_limit_org: int | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Prompt Gallery API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(RequestIDMiddleware)

    app.add_middleware(
        RateLimitMiddleware,
        limit_anonymous=rate_limit_anonymous if rate_limit_anonymous is not None else settings.RATE_LIMIT_ANONYMOUS,
        limit_user=rate_limit_user if rate_limit_user is not None else settings.RATE_LIMIT_USER,
        limit_azp=rate_limit_azp if rate_limit_azp is not None else settings.RATE_LIMIT_CLIENT,
        limit_org=rate_limit_org if rate_limit_org is not None else settings.RATE_LIMIT_ORG,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    prefix = "/api/v1"
    app.include_router(health.router, prefix=prefix)
    app.include_router(categories.router, prefix=prefix)
    app.include_router(tags.router, prefix=prefix)
    app.include_router(prompts.router, prefix=prefix)
    app.include_router(me.router, prefix=prefix)
    app.include_router(uploads.router, prefix=prefix)
    app.include_router(admin.router, prefix=prefix)

    _install_openapi(app)

    return app


app = create_app()
