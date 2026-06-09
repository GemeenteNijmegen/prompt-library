"""
Contract tests for the MCP sidecar Docker topology (issue #71).

Parse docker-compose.yml, Dockerfile.mcp, requirements-mcp.txt, and .env.example
to assert the compose configuration matches the topology in ADR 0005:
  chat client → MCP sidecar → gallery REST API.

No Docker daemon required — all assertions are pure YAML/text parsing.
"""
import pathlib
import pytest
import yaml

ROOT = pathlib.Path(__file__).parent.parent


def _compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())


def _dockerfile_mcp() -> str:
    return (ROOT / "Dockerfile.mcp").read_text()


def _requirements_mcp() -> str:
    return (ROOT / "requirements-mcp.txt").read_text()


def _env_example() -> str:
    return (ROOT / ".env.example").read_text()


# ── Dockerfile.mcp ────────────────────────────────────────────────────────────


def test_dockerfile_mcp_exists():
    assert (ROOT / "Dockerfile.mcp").exists()


def test_dockerfile_mcp_copies_gallery_mcp():
    assert "gallery_mcp" in _dockerfile_mcp()


def test_dockerfile_mcp_exposes_8001():
    assert "8001" in _dockerfile_mcp()


def test_dockerfile_mcp_cmd_runs_gallery_mcp_module():
    text = _dockerfile_mcp()
    assert "gallery_mcp" in text
    assert "CMD" in text


# ── requirements-mcp.txt ─────────────────────────────────────────────────────


def test_requirements_mcp_exists():
    assert (ROOT / "requirements-mcp.txt").exists()


def test_requirements_mcp_contains_mcp():
    assert "mcp" in _requirements_mcp()


def test_requirements_mcp_contains_httpx():
    assert "httpx" in _requirements_mcp()


def test_requirements_mcp_contains_uvicorn():
    assert "uvicorn" in _requirements_mcp()


def test_requirements_mcp_contains_pydantic_settings():
    assert "pydantic-settings" in _requirements_mcp()


def test_requirements_mcp_excludes_heavy_gallery_deps():
    """Sidecar image must not pull in gallery-only heavyweights."""
    text = _requirements_mcp()
    for dep in ("fastembed", "alembic", "sqlalchemy", "boto3", "psycopg2"):
        assert dep not in text, f"requirements-mcp.txt must not include {dep}"


# ── docker-compose.yml — mcp service ─────────────────────────────────────────


def test_mcp_service_present():
    assert "mcp" in _compose()["services"]


def test_mcp_service_uses_dockerfile_mcp():
    build = _compose()["services"]["mcp"].get("build", {})
    assert isinstance(build, dict), "mcp build must be a mapping (not a bare string)"
    assert build.get("dockerfile") == "Dockerfile.mcp"


def test_mcp_service_exposes_8001():
    ports = _compose()["services"]["mcp"].get("ports", [])
    assert any("8001" in str(p) for p in ports)


def test_mcp_service_gallery_api_url_present():
    env = _compose()["services"]["mcp"].get("environment", {})
    if isinstance(env, list):
        keys = [e.split("=")[0] for e in env]
    else:
        keys = list(env.keys())
    assert "GALLERY_API_URL" in keys


def test_mcp_service_gallery_api_url_uses_internal_hostname():
    """GALLERY_API_URL must use a Docker-internal service name, not localhost."""
    env = _compose()["services"]["mcp"].get("environment", {})
    if isinstance(env, dict):
        url = env.get("GALLERY_API_URL", "")
    else:
        url = next(
            (e.split("=", 1)[1] for e in env if e.startswith("GALLERY_API_URL=")), ""
        )
    assert "localhost" not in url, "GALLERY_API_URL must use Docker service name, not localhost"
    assert url.startswith("http://"), f"GALLERY_API_URL must be an http URL, got: {url!r}"


def test_mcp_service_profile_includes_full():
    profiles = _compose()["services"]["mcp"].get("profiles", [])
    assert "full" in profiles


def test_mcp_service_depends_on_app():
    """MCP sidecar must declare a dependency on the gallery app service."""
    depends = _compose()["services"]["mcp"].get("depends_on", {})
    if isinstance(depends, list):
        assert "app" in depends
    else:
        assert "app" in depends


# ── docker-compose.yml — mcp-dev service ─────────────────────────────────────


def test_mcp_dev_service_present():
    assert "mcp-dev" in _compose()["services"]


def test_mcp_dev_profile_includes_dev():
    profiles = _compose()["services"]["mcp-dev"].get("profiles", [])
    assert "dev" in profiles


def test_mcp_dev_gallery_api_url_points_to_app_dev():
    """mcp-dev must talk to app-dev, not the production app service."""
    env = _compose()["services"]["mcp-dev"].get("environment", {})
    if isinstance(env, dict):
        url = env.get("GALLERY_API_URL", "")
    else:
        url = next(
            (e.split("=", 1)[1] for e in env if e.startswith("GALLERY_API_URL=")), ""
        )
    assert "app-dev" in url, f"mcp-dev GALLERY_API_URL must point to app-dev, got: {url!r}"


def test_mcp_dev_mounts_gallery_mcp_volume():
    """mcp-dev must mount ./gallery_mcp for live code reloading."""
    volumes = _compose()["services"]["mcp-dev"].get("volumes", [])
    assert any("gallery_mcp" in str(v) for v in volumes)


def test_mcp_dev_depends_on_app_dev():
    depends = _compose()["services"]["mcp-dev"].get("depends_on", {})
    if isinstance(depends, list):
        assert "app-dev" in depends
    else:
        assert "app-dev" in depends


# ── .env.example ─────────────────────────────────────────────────────────────


def test_env_example_has_mcp_port():
    assert "MCP_PORT" in _env_example()


def test_env_example_has_mcp_resource_url():
    assert "MCP_RESOURCE_URL" in _env_example()


def test_env_example_has_keycloak_realm_url():
    assert "KEYCLOAK_REALM_URL" in _env_example()
