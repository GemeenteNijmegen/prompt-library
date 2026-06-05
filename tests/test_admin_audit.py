"""Unit tests for GET /api/v1/admin/audit.

Verifies scope gating and basic query/filter behaviour against the real DB.
"""
import pytest

from src.models.prompt_event import PromptEvent
from src.services.audit_service import write_event
from tests.conftest import TEST_AZP, make_jwt


def _write_event(client, sub: str, azp: str, title: str = "t") -> dict:
    """Create a prompt as `sub`/`azp` so an audit event is written, return prompt data."""
    token = make_jwt(sub=sub, azp=azp)
    r = client.post(
        "/api/v1/prompts",
        json={
            "title": title,
            "description": "audit unit test",
            "prompt_text": "x",
            "status": "draft",
            "visibility": "public",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


def test_admin_audit_requires_read_audit_scope(client):
    token = make_jwt(scope=["prompt:read"])
    r = client.get("/api/v1/admin/audit", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_audit_returns_events(client):
    prompt = _write_event(client, "audit-user-1", "client-a")
    r = client.get(
        "/api/v1/admin/audit",
        params={"entity_type": "prompt", "entity_id": str(prompt["id"])},
        headers={"Authorization": f"Bearer {make_jwt()}"},
    )
    assert r.status_code == 200
    events = r.json()["data"]
    assert any(e["action"] == "created" for e in events)


def test_admin_audit_client_id_matches_azp(client):
    azp = "my-special-client"
    prompt = _write_event(client, "audit-user-2", azp, title="azp-check")
    r = client.get(
        "/api/v1/admin/audit",
        params={"entity_type": "prompt", "entity_id": str(prompt["id"])},
        headers={"Authorization": f"Bearer {make_jwt()}"},
    )
    events = r.json()["data"]
    created = [e for e in events if e["action"] == "created"]
    assert created, "Expected a 'created' event"
    assert created[0]["client_id"] == azp


def test_admin_audit_filters_by_entity_type(client):
    prompt = _write_event(client, "audit-user-3", TEST_AZP, title="filter-test")
    r = client.get(
        "/api/v1/admin/audit",
        params={"entity_type": "nonexistent_type", "entity_id": str(prompt["id"])},
        headers={"Authorization": f"Bearer {make_jwt()}"},
    )
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_admin_audit_limit_respected(client):
    """limit=1 returns at most one event."""
    r = client.get(
        "/api/v1/admin/audit",
        params={"limit": 1},
        headers={"Authorization": f"Bearer {make_jwt()}"},
    )
    assert r.status_code == 200
    assert len(r.json()["data"]) <= 1


def test_admin_audit_requires_auth(client):
    r = client.get("/api/v1/admin/audit")
    assert r.status_code == 401
