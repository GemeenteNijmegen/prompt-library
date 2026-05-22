import os
import pytest
from starlette.testclient import TestClient
from tests.conftest import make_jwt


def make_rate_limited_client(db, anon_limit=3, user_limit=5, machine_limit=8):
    from src.main import create_app
    from src.dependencies import get_db
    from src.middleware.rate_limit import RateLimitMiddleware

    app = create_app(
        rate_limit_anonymous=anon_limit,
        rate_limit_user=user_limit,
        rate_limit_machine=machine_limit,
    )

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def rl_client(db):
    yield from make_rate_limited_client(db)


def test_anonymous_caller_hits_limit(rl_client):
    limit = 3
    for i in range(limit):
        resp = rl_client.get("/api/v1/health")
        assert resp.status_code == 200, f"Expected 200 on request {i + 1}"
    # Next request should be rate-limited
    resp = rl_client.get("/api/v1/health")
    assert resp.status_code == 429
    body = resp.json()
    assert body["error"]["code"] == "RATE_LIMITED"


def test_authenticated_user_has_higher_limit(db):
    # user limit=5, anon limit=3 — so request 4 passes for user but not anon
    yield_gen = make_rate_limited_client(db, anon_limit=3, user_limit=5, machine_limit=10)
    client = next(yield_gen)
    token = make_jwt(scope=["prompt:read"])
    headers = {"Authorization": f"Bearer {token}"}
    for i in range(5):
        resp = client.get("/api/v1/health", headers=headers)
        assert resp.status_code == 200, f"Expected 200 on user request {i + 1}"
    resp = client.get("/api/v1/health", headers=headers)
    assert resp.status_code == 429


def test_machine_token_has_highest_limit(db):
    yield_gen = make_rate_limited_client(db, anon_limit=3, user_limit=5, machine_limit=8)
    client = next(yield_gen)
    token = make_jwt(scope=["prompt:read"], machine=True)
    headers = {"Authorization": f"Bearer {token}"}
    for i in range(8):
        resp = client.get("/api/v1/health", headers=headers)
        assert resp.status_code == 200, f"Expected 200 on machine request {i + 1}"
    resp = client.get("/api/v1/health", headers=headers)
    assert resp.status_code == 429


def test_429_response_shape(rl_client):
    limit = 3
    for _ in range(limit):
        rl_client.get("/api/v1/health")
    resp = rl_client.get("/api/v1/health")
    assert resp.status_code == 429
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "RATE_LIMITED"
    assert "message" in body["error"]
