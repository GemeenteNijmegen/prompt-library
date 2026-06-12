"""
Contract tests for the Docker release workflow (issue #81).

Parse .github/workflows/docker.yml to assert the workflow builds and pushes
both the library image and the MCP sidecar image on main/tags.

No network or Docker daemon required — pure YAML parsing.
"""
import pathlib
import pytest
import yaml

ROOT = pathlib.Path(__file__).parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "docker.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _all_steps() -> list[dict]:
    jobs = _workflow().get("jobs", {})
    steps = []
    for job in jobs.values():
        steps.extend(job.get("steps", []))
    return steps


def _build_push_steps() -> list[dict]:
    return [
        s for s in _all_steps()
        if "docker/build-push-action" in str(s.get("uses", ""))
    ]


def _metadata_steps() -> list[dict]:
    return [
        s for s in _all_steps()
        if "docker/metadata-action" in str(s.get("uses", ""))
    ]


# ── Workflow file ─────────────────────────────────────────────────────────────


def test_workflow_file_exists():
    assert WORKFLOW.exists()


# ── MCP build job: uses Dockerfile.mcp ───────────────────────────────────────


def test_mcp_build_step_exists():
    """At least one build-push step must reference Dockerfile.mcp."""
    mcp_steps = [
        s for s in _build_push_steps()
        if "Dockerfile.mcp" in str(s.get("with", {}).get("file", ""))
    ]
    assert mcp_steps, "No build-push step found that references Dockerfile.mcp"


# ── MCP image name uses -mcp suffix ──────────────────────────────────────────


def test_mcp_image_name_has_mcp_suffix():
    """Metadata step for MCP must publish to a -mcp-suffixed image name."""
    mcp_meta = [
        s for s in _metadata_steps()
        if "-mcp" in str(s.get("with", {}).get("images", ""))
    ]
    assert mcp_meta, "No metadata step found with a -mcp-suffixed image name"


# ── MCP tag strategy mirrors library ─────────────────────────────────────────


def test_mcp_metadata_has_latest_tag():
    """MCP metadata step must produce a 'latest' tag on main."""
    mcp_meta = [
        s for s in _metadata_steps()
        if "-mcp" in str(s.get("with", {}).get("images", ""))
    ]
    assert mcp_meta, "No MCP metadata step found"
    tags = mcp_meta[0].get("with", {}).get("tags", "")
    assert "latest" in str(tags), "MCP metadata step must include a 'latest' tag rule"


def test_mcp_metadata_has_semver_tag():
    """MCP metadata step must produce semver tags on v* releases."""
    mcp_meta = [
        s for s in _metadata_steps()
        if "-mcp" in str(s.get("with", {}).get("images", ""))
    ]
    tags = mcp_meta[0].get("with", {}).get("tags", "")
    assert "ref,event=tag" in str(tags) or "semver" in str(tags), (
        "MCP metadata step must include a semver/tag-ref tag rule"
    )
