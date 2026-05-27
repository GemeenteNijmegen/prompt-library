import os
import pytest
from starlette.testclient import TestClient
from tests.conftest import make_jwt, TEST_ORG_ID, TEST_AZP


def make_rate_limited_client(db, anon_limit=3, user_limit=5, azp_limit=10, org_limit=20):
    from src.main import create_app
    from src.dependencies import get_db

    app = create_app(
        rate_limit_anonymous=anon_limit,
        rate_limit_user=user_limit,
        rate_limit_azp=azp_limit,
        rate_limit_org=org_limit,
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
    resp = rl_client.get("/api/v1/health")
    assert resp.status_code == 429
    body = resp.json()
    assert body["error"]["code"] == "RATE_LIMITED"


def test_authenticated_user_has_higher_limit(db):
    # user limit=5, anon limit=3 — request 4 passes for auth but not anon
    yield_gen = make_rate_limited_client(db, anon_limit=3, user_limit=5)
    client = next(yield_gen)
    token = make_jwt(scope=["prompt:read"], azp="", org_id="")
    headers = {"Authorization": f"Bearer {token}"}
    for i in range(5):
        resp = client.get("/api/v1/health", headers=headers)
        assert resp.status_code == 200, f"Expected 200 on user request {i + 1}"
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


def test_per_azp_bucket_enforced(db):
    """Requests from the same OAuth client (azp) share a per-azp bucket."""
    azp_limit = 3
    yield_gen = make_rate_limited_client(db, user_limit=100, azp_limit=azp_limit, org_limit=100)
    client = next(yield_gen)

    # Two different users but same azp — they share the azp bucket
    token_a = make_jwt(sub="user-a", azp=TEST_AZP, org_id="")
    token_b = make_jwt(sub="user-b", azp=TEST_AZP, org_id="")

    for i in range(azp_limit):
        resp = client.get("/api/v1/health", headers={"Authorization": f"Bearer {token_a}"})
        assert resp.status_code == 200

    # user-b uses same azp — the shared azp bucket is exhausted
    resp = client.get("/api/v1/health", headers={"Authorization": f"Bearer {token_b}"})
    assert resp.status_code == 429


def test_per_org_bucket_enforced(db):
    """Requests from the same org share an org-level bucket."""
    org_limit = 3
    yield_gen = make_rate_limited_client(db, user_limit=100, azp_limit=100, org_limit=org_limit)
    client = next(yield_gen)

    token_a = make_jwt(sub="user-a", azp="client-a", org_id=TEST_ORG_ID)
    token_b = make_jwt(sub="user-b", azp="client-b", org_id=TEST_ORG_ID)

    for i in range(org_limit):
        resp = client.get("/api/v1/health", headers={"Authorization": f"Bearer {token_a}"})
        assert resp.status_code == 200

    # user-b same org — org bucket exhausted
    resp = client.get("/api/v1/health", headers={"Authorization": f"Bearer {token_b}"})
    assert resp.status_code == 429


def test_different_orgs_independent_buckets(db):
    """Users in different orgs don't share the org bucket."""
    org_limit = 2
    yield_gen = make_rate_limited_client(db, user_limit=100, azp_limit=100, org_limit=org_limit)
    client = next(yield_gen)

    token_a = make_jwt(sub="user-a", azp="client-a", org_id="org-alpha")
    token_b = make_jwt(sub="user-b", azp="client-b", org_id="org-beta")

    # Exhaust org-alpha's bucket
    for _ in range(org_limit):
        resp = client.get("/api/v1/health", headers={"Authorization": f"Bearer {token_a}"})
        assert resp.status_code == 200

    # org-beta is unaffected
    resp = client.get("/api/v1/health", headers={"Authorization": f"Bearer {token_b}"})
    assert resp.status_code == 200
