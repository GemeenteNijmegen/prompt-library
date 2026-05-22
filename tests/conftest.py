import os
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from starlette.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DEV_STUB_TOKEN", "dev-token")
os.environ.setdefault("ENVIRONMENT", "testing")

from src.models import Base
from src.main import create_app
from src.dependencies import get_db

TEST_DB_URL = "sqlite:///:memory:"

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


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


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
    return {"Authorization": "Bearer dev-token"}


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
