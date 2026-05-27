"""Row-level visibility tests — CONTEXT.md §Visibility model."""
import os
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["ENVIRONMENT"] = "testing"
os.environ["JWT_SECRET_KEY"] = "test-secret-key"
os.environ["JWKS_URI"] = ""

from tests.conftest import make_jwt, TEST_ORG_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_prompt(db, creator_user, status="published_org", visibility="public"):
    from src.models.prompt import Prompt
    p = Prompt(
        title=f"Prompt {status}",
        description="desc",
        prompt_text="text",
        status=status,
        visibility=visibility,
        featured=False,
        creator_id=creator_user.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _make_user(db, external_id, org_id):
    from src.models.user import User
    u = User(external_id=external_id, org_id=org_id, name=external_id, email=f"{external_id}@test.com")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ---------------------------------------------------------------------------
# Anonymous access
# ---------------------------------------------------------------------------

def test_anon_sees_published_public(client, db, dev_user):
    p = _create_prompt(db, dev_user, status="published_public")
    r = client.get(f"/api/v1/prompts/{p.id}")
    assert r.status_code == 200


def test_anon_cannot_see_published_org(client, db, dev_user):
    p = _create_prompt(db, dev_user, status="published_org")
    r = client.get(f"/api/v1/prompts/{p.id}")
    assert r.status_code == 404


def test_anon_cannot_see_draft(client, db, dev_user):
    p = _create_prompt(db, dev_user, status="draft")
    r = client.get(f"/api/v1/prompts/{p.id}")
    assert r.status_code == 404


def test_anon_cannot_see_archived(client, db, dev_user):
    p = _create_prompt(db, dev_user, status="archived")
    r = client.get(f"/api/v1/prompts/{p.id}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Authenticated — same-org
# ---------------------------------------------------------------------------

def test_same_org_user_sees_published_org(client, auth_headers, db, dev_user):
    p = _create_prompt(db, dev_user, status="published_org")
    r = client.get(f"/api/v1/prompts/{p.id}", headers=auth_headers)
    assert r.status_code == 200


def test_same_org_user_cannot_see_cross_org_published_org(client, db, dev_user):
    other_user = _make_user(db, "other-org-user", org_id="other-org-999")
    p = _create_prompt(db, other_user, status="published_org")

    token = make_jwt(sub="dev-user-001", org_id=TEST_ORG_ID)
    r = client.get(f"/api/v1/prompts/{p.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


def test_author_sees_own_draft(client, db, dev_user):
    p = _create_prompt(db, dev_user, status="draft")
    token = make_jwt(sub="dev-user-001", org_id=TEST_ORG_ID)
    r = client.get(f"/api/v1/prompts/{p.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_non_author_cannot_see_other_org_draft(client, db, dev_user):
    other_user = _make_user(db, "draft-owner", org_id="other-org-999")
    p = _create_prompt(db, other_user, status="draft")

    token = make_jwt(sub="dev-user-001", org_id=TEST_ORG_ID)
    r = client.get(f"/api/v1/prompts/{p.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


def test_non_author_same_org_cannot_see_draft_without_admin(client, db, dev_user):
    """A regular org member cannot see another member's draft."""
    peer = _make_user(db, "peer-user", org_id=TEST_ORG_ID)
    p = _create_prompt(db, peer, status="draft")

    token = make_jwt(sub="dev-user-001", org_id=TEST_ORG_ID, scope=["prompt:read"])
    r = client.get(f"/api/v1/prompts/{p.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


def test_org_admin_sees_same_org_draft(client, db, dev_user):
    """An org admin (admin:manage_users scope) can see drafts from their org."""
    peer = _make_user(db, "draft-author", org_id=TEST_ORG_ID)
    p = _create_prompt(db, peer, status="draft")

    token = make_jwt(sub="dev-user-001", org_id=TEST_ORG_ID, scope=["prompt:read", "admin:manage_users"])
    r = client.get(f"/api/v1/prompts/{p.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_org_admin_cannot_see_other_org_draft(client, db):
    """Even an org admin cannot see drafts from a different org."""
    other_user = _make_user(db, "other-draft-author", org_id="other-org-999")
    p = _create_prompt(db, other_user, status="draft")

    token = make_jwt(sub="dev-user-001", org_id=TEST_ORG_ID, scope=["prompt:read", "admin:manage_users"])
    r = client.get(f"/api/v1/prompts/{p.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# List endpoint applies same filter
# ---------------------------------------------------------------------------

def test_list_excludes_cross_org_published_org(client, db, dev_user):
    other_user = _make_user(db, "cross-org-author", org_id="different-org-888")
    cross_org_prompt = _create_prompt(db, other_user, status="published_org")

    token = make_jwt(sub="dev-user-001", org_id=TEST_ORG_ID)
    r = client.get("/api/v1/prompts", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()["data"]]
    assert cross_org_prompt.id not in ids


def test_anon_list_only_shows_published_public(client, db, dev_user):
    pub = _create_prompt(db, dev_user, status="published_public")
    _create_prompt(db, dev_user, status="published_org")
    _create_prompt(db, dev_user, status="draft")

    r = client.get("/api/v1/prompts")
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()["data"]]
    assert pub.id in ids
    # Only published_public prompts are returned for anonymous callers
    for item in r.json()["data"]:
        assert item["status"] == "published_public"


# ---------------------------------------------------------------------------
# Status transitions — prompt:publish:public gate
# ---------------------------------------------------------------------------

def test_publish_public_requires_scope(client, auth_headers, db, dev_user):
    """prompt:publish:public scope is required to transition to published_public."""
    from src.models.prompt import Prompt
    p = Prompt(
        title="Scope Gate Test",
        description="desc",
        prompt_text="text",
        status="published_org",
        visibility="public",
        featured=False,
        creator_id=dev_user.id,
    )
    db.add(p)
    db.commit()

    # Token with prompt:publish but NOT prompt:publish:public
    token = make_jwt(scope=["prompt:read", "prompt:write", "prompt:publish"])
    r = client.patch(
        f"/api/v1/prompts/{p.id}",
        json={"status": "published_public"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    assert "publish:public" in r.json()["detail"]["error"]["message"]


def test_publish_public_succeeds_with_scope(client, db, dev_user):
    """prompt:publish:public scope allows the published_org → published_public transition."""
    from src.models.prompt import Prompt
    p = Prompt(
        title="Scope Gate Success",
        description="desc",
        prompt_text="text",
        status="published_org",
        visibility="public",
        featured=False,
        creator_id=dev_user.id,
    )
    db.add(p)
    db.commit()

    token = make_jwt(scope=["prompt:read", "prompt:write", "prompt:publish", "prompt:publish:public"])
    r = client.patch(
        f"/api/v1/prompts/{p.id}",
        json={"status": "published_public"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "published_public"
