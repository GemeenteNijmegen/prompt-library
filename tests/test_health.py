from starlette.testclient import TestClient


def test_health_ok(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["status"] == "ok"
    assert body["data"]["version"] == "0.1.0"


def test_health_db_unavailable():
    """Health returns 503 when DB is unreachable."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from src.main import create_app
    from src.dependencies import get_db

    bad_engine = create_engine("sqlite:////nonexistent/path/db.sqlite")

    app = create_app()

    def override_bad_db():
        s = Session(bind=bad_engine)
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_bad_db

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/v1/health")
    assert r.status_code == 503
