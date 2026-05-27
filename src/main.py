import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.database import init_db
from src.middleware.rate_limit import RateLimitMiddleware
from src.middleware.request_id import RequestIDMiddleware
from src.routers import health, categories, tags, prompts, auth, uploads

logging.basicConfig(
    level=settings.LOG_LEVEL.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logging.getLogger("sqlalchemy").propagate = False
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — environment=%s", settings.ENVIRONMENT)
    init_db()
    yield
    logger.info("Shutting down")


def create_app(
    rate_limit_anonymous: int | None = None,
    rate_limit_user: int | None = None,
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
    app.include_router(auth.router, prefix=prefix)
    app.include_router(uploads.router, prefix=prefix)

    return app


app = create_app()
