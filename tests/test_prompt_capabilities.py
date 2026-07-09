"""Per-prompt capability flags — see docs/adr/0006-surrogate-user-key-and-per-prompt-capabilities.md."""
from tests.conftest import make_jwt, TEST_ORG_ID


def _create_prompt(db, creator_user, status="published_public", visibility="public", featured=False):
    from src.models.prompt import Prompt
    p = Prompt(
        title=f"Prompt {status}",
        description="desc",
        prompt_text="text",
        status=status,
        visibility=visibility,
        featured=featured,
        creator_id=creator_user.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _make_user(db, external_id, org_id=TEST_ORG_ID):
    from src.models.user import User
    u = User(external_id=external_id, org_id=org_id, name=external_id, email=f"{external_id}@test.com")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ---------------------------------------------------------------------------
# can_edit / can_delete — owner, moderator, unrelated caller
# ---------------------------------------------------------------------------

def test_owner_sees_can_edit_and_can_delete_true(client, db, dev_user):
    p = _create_prompt(db, dev_user, status="draft")
    token = make_jwt(sub="dev-user-001", org_id=TEST_ORG_ID, scope=["prompt:read"])
    r = client.get(f"/api/v1/prompts/{p.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["can_edit"] is True
    assert data["can_delete"] is True


def test_unrelated_caller_without_moderate_sees_can_edit_false(client, db, dev_user):
    p = _create_prompt(db, dev_user, status="published_public")
    other = _make_user(db, "unrelated-user")
    token = make_jwt(sub="unrelated-user", org_id=TEST_ORG_ID, scope=["prompt:read"])
    r = client.get(f"/api/v1/prompts/{p.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["can_edit"] is False
    assert data["can_delete"] is False
    assert data["can_publish"] is False
    assert data["can_feature"] is False


def test_moderator_sees_can_edit_and_can_delete_true_on_others_prompt(client, db, dev_user):
    p = _create_prompt(db, dev_user, status="published_public")
    token = make_jwt(sub="moderator-user", org_id=TEST_ORG_ID, scope=["prompt:read", "prompt:moderate"])
    r = client.get(f"/api/v1/prompts/{p.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["can_edit"] is True
    assert data["can_delete"] is True
    assert data["can_feature"] is True


def test_moderator_can_fetch_and_edit_others_draft_prompt(client, db, dev_user):
    """Regression: visibility_filter() must let prompt:moderate through on draft/
    published_org rows too, or a moderator gets told can_edit=true (via
    prompt_capabilities) for a prompt that then 404s on GET/PATCH — reported as
    'Prompt not found' when a platform-admin (prompt:moderate, no
    admin:manage_users) edited another user's draft prompt."""
    p = _create_prompt(db, dev_user, status="draft")
    token = make_jwt(sub="moderator-user", org_id=TEST_ORG_ID, scope=["prompt:read", "prompt:write", "prompt:moderate"])

    get_resp = client.get(f"/api/v1/prompts/{p.id}", headers={"Authorization": f"Bearer {token}"})
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["can_edit"] is True

    patch_resp = client.patch(
        f"/api/v1/prompts/{p.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "Edited by moderator"},
    )
    assert patch_resp.status_code == 200

    get_again = client.get(f"/api/v1/prompts/{p.id}", headers={"Authorization": f"Bearer {token}"})
    assert get_again.status_code == 200
    assert get_again.json()["data"]["title"] == "Edited by moderator"


def test_anonymous_caller_sees_all_flags_false(client, sample_prompt):
    r = client.get(f"/api/v1/prompts/{sample_prompt.id}")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["can_edit"] is False
    assert data["can_delete"] is False
    assert data["can_publish"] is False
    assert data["can_feature"] is False


# ---------------------------------------------------------------------------
# can_publish — owner + prompt:publish, or moderate
# ---------------------------------------------------------------------------

def test_owner_with_publish_scope_sees_can_publish_true(client, db, dev_user):
    p = _create_prompt(db, dev_user, status="draft")
    token = make_jwt(sub="dev-user-001", org_id=TEST_ORG_ID, scope=["prompt:read", "prompt:publish"])
    r = client.get(f"/api/v1/prompts/{p.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["data"]["can_publish"] is True


def test_owner_without_publish_scope_sees_can_publish_false(client, db, dev_user):
    p = _create_prompt(db, dev_user, status="draft")
    token = make_jwt(sub="dev-user-001", org_id=TEST_ORG_ID, scope=["prompt:read"])
    r = client.get(f"/api/v1/prompts/{p.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["data"]["can_publish"] is False


def test_moderator_sees_can_publish_true_without_owning(client, db, dev_user):
    p = _create_prompt(db, dev_user, status="published_public")
    token = make_jwt(sub="moderator-user", org_id=TEST_ORG_ID, scope=["prompt:read", "prompt:moderate"])
    r = client.get(f"/api/v1/prompts/{p.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["data"]["can_publish"] is True


# ---------------------------------------------------------------------------
# can_feature — moderate only
# ---------------------------------------------------------------------------

def test_owner_without_moderate_sees_can_feature_false(client, db, dev_user):
    p = _create_prompt(db, dev_user, status="draft")
    token = make_jwt(sub="dev-user-001", org_id=TEST_ORG_ID, scope=["prompt:read", "prompt:write", "prompt:publish"])
    r = client.get(f"/api/v1/prompts/{p.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["data"]["can_feature"] is False


# ---------------------------------------------------------------------------
# Flags present on list (summary), create/update echoes, and cover both schemas
# ---------------------------------------------------------------------------

def test_list_summary_includes_capability_flags(client, auth_headers, sample_prompt):
    r = client.get("/api/v1/prompts", headers=auth_headers)
    assert r.status_code == 200
    item = next(i for i in r.json()["data"] if i["id"] == sample_prompt.id)
    for flag in ("can_edit", "can_delete", "can_publish", "can_feature"):
        assert flag in item


def test_create_response_includes_capability_flags(client, auth_headers):
    r = client.post("/api/v1/prompts", json={
        "title": "Cap Flags",
        "description": "desc",
        "prompt_text": "text",
    }, headers=auth_headers)
    assert r.status_code == 201
    data = r.json()["data"]
    # Creator owns the new prompt.
    assert data["can_edit"] is True
    assert data["can_delete"] is True


def test_update_response_includes_capability_flags(client, auth_headers, sample_prompt):
    r = client.patch(
        f"/api/v1/prompts/{sample_prompt.id}",
        json={"title": "Updated"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["can_edit"] is True


# ---------------------------------------------------------------------------
# Featured cache must key on caller identity (ADR 0006 consequence)
# ---------------------------------------------------------------------------

def test_featured_cache_does_not_leak_flags_between_callers(client, db, dev_user):
    p = _create_prompt(db, dev_user, status="published_public", featured=True)

    owner_token = make_jwt(sub="dev-user-001", org_id=TEST_ORG_ID, scope=["prompt:read"])
    r_owner = client.get("/api/v1/prompts/featured", headers={"Authorization": f"Bearer {owner_token}"})
    assert r_owner.status_code == 200
    owner_item = next(i for i in r_owner.json()["data"] if i["id"] == p.id)
    assert owner_item["can_edit"] is True

    other_token = make_jwt(sub="unrelated-user", org_id=TEST_ORG_ID, scope=["prompt:read"])
    r_other = client.get("/api/v1/prompts/featured", headers={"Authorization": f"Bearer {other_token}"})
    assert r_other.status_code == 200
    other_item = next(i for i in r_other.json()["data"] if i["id"] == p.id)
    assert other_item["can_edit"] is False

    r_anon = client.get("/api/v1/prompts/featured")
    assert r_anon.status_code == 200
    anon_item = next(i for i in r_anon.json()["data"] if i["id"] == p.id)
    assert anon_item["can_edit"] is False
