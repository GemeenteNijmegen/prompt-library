import os
import time

import pytest
from jose import jwt
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from starlette.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["ENVIRONMENT"] = "testing"
os.environ["JWT_SECRET_KEY"] = "test-secret-key"
os.environ["JWKS_URI"] = ""
os.environ["EMBEDDING_USE_FAKE"] = "true"

from src.models import Base
from src.main import create_app
from src.dependencies import get_db

TEST_DB_URL = "sqlite:///:memory:"
_JWT_SECRET = "test-secret-key"
_JWT_ISSUER = "http://localhost:9000"

engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
)


def _set_pragma(dbapi_conn, _record):
    c = dbapi_conn.cursor()
    c.execute("PRAGMA foreign_keys=ON")
    c.close()


event.listen(engine, "connect", _set_pragma)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def make_jwt(
    sub: str = "dev-user-001",
    name: str = "Dev User",
    email: str = "dev@example.com",
    avatar_url: str | None = None,
    scope: list[str] | None = None,
    expired: bool = False,
    machine: bool = False,
) -> str:
    if scope is None:
        scope = [
            "prompt:read",
            "prompt:read:restricted",
            "prompt:create",
            "prompt:write",
            "prompt:publish",
            "prompt:rate",
            "prompt:image",
            "admin:manage_taxonomy",
            "admin:manage_keys",
            "admin:manage_users",
        ]
    now = int(time.time())
    payload = {
        "sub": sub,
        "scope": scope,
        "name": name,
        "email": email,
        "avatar_url": avatar_url,
        "iss": _JWT_ISSUER,
        "iat": now - 10,
        "exp": (now - 120) if expired else (now + 3600),  # 120 s exceeds the 60 s leeway
    }
    if machine:
        payload["token_type"] = "machine"
    return jwt.encode(payload, _JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def reset_vector_cache():
    from src.services import prompt_service
    prompt_service._invalidate_vector_cache()
    yield
    prompt_service._invalidate_vector_cache()


@pytest.fixture()
def db() -> Session:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db: Session):
    app = create_app()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def auth_headers():
    return {"Authorization": f"Bearer {make_jwt()}"}


@pytest.fixture()
def dev_user(db: Session):
    from src.models.user import User
    user = db.query(User).filter(User.external_id == "dev-user-001").first()
    if not user:
        user = User(external_id="dev-user-001", name="Dev User", email="dev@example.com")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@pytest.fixture()
def sample_category(db: Session):
    from src.models.category import PromptCategory
    cat = PromptCategory(name="Test Category", description="A test category")
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@pytest.fixture()
def sample_tag(db: Session):
    from src.models.tag import PromptTag
    tag = PromptTag(name="test-tag")
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@pytest.fixture()
def sample_prompt(db: Session, dev_user):
    from src.models.prompt import Prompt
    p = Prompt(
        title="Sample Prompt",
        description="A sample description",
        prompt_text="Write something about {topic}",
        status="published",
        visibility="public",
        featured=False,
        creator_id=dev_user.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p
