from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from src.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    echo=(settings.LOG_LEVEL == "debug"),
)


def _set_sqlite_pragma(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


if "sqlite" in settings.DATABASE_URL:
    event.listen(engine, "connect", _set_sqlite_pragma)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from src.models import Base  # noqa: F401 — registers all models
    Base.metadata.create_all(bind=engine)
