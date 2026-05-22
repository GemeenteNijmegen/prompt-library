"""Tests for X-Request-ID middleware and structured logging."""
import json
import uuid
import logging

import pytest


@pytest.fixture(autouse=True)
def reset_cache():
    import src.cache as cache_mod
    cache_mod.cache_clear()
    yield
    cache_mod.cache_clear()


def test_response_has_request_id_header(client):
    resp = client.get("/api/v1/health")
    assert "x-request-id" in resp.headers


def test_caller_supplied_request_id_is_echoed(client):
    supplied_id = "my-custom-request-id-123"
    resp = client.get("/api/v1/health", headers={"X-Request-ID": supplied_id})
    assert resp.headers["x-request-id"] == supplied_id


def test_generated_request_id_is_valid_uuid(client):
    resp = client.get("/api/v1/health")
    request_id = resp.headers["x-request-id"]
    parsed = uuid.UUID(request_id)
    assert str(parsed) == request_id


def test_all_responses_have_request_id(client):
    for path in ["/api/v1/health", "/api/v1/categories", "/api/v1/tags"]:
        resp = client.get(path)
        assert "x-request-id" in resp.headers, f"Missing X-Request-ID on {path}"


def test_log_includes_request_id(client, caplog):
    supplied_id = "log-trace-id-abc"
    with caplog.at_level(logging.INFO, logger="src.middleware.request_id"):
        resp = client.get("/api/v1/health", headers={"X-Request-ID": supplied_id})
    assert any(supplied_id in record.message for record in caplog.records)


def test_log_includes_required_fields(client, caplog):
    with caplog.at_level(logging.INFO, logger="src.middleware.request_id"):
        resp = client.get("/api/v1/health")
    messages = " ".join(r.message for r in caplog.records)
    assert "GET" in messages
    assert "/api/v1/health" in messages
    assert str(resp.status_code) in messages
