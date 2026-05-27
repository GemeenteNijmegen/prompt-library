"""Tests that every state-changing endpoint writes a prompt_events row."""

import pytest
from tests.conftest import make_jwt, TEST_ORG_ID, TEST_AZP
from src.models.prompt_event import PromptEvent


def _events(db, **filters):
    q = db.query(PromptEvent)
    for k, v in filters.items():
        q = q.filter(getattr(PromptEvent, k) == v)
    return q.all()


# ── Prompts ───────────────────────────────────────────────────────────────────

def test_create_prompt_writes_event(client, db, auth_headers):
    r = client.post("/api/v1/prompts", json={
        "title": "Audit Prompt",
        "description": "desc",
        "prompt_text": "Write about {x}",
        "status": "draft",
    }, headers=auth_headers)
    assert r.status_code == 201
    prompt_id = r.json()["data"]["id"]
    evts = _events(db, entity_type="prompt", entity_id=str(prompt_id), action="created")
    assert len(evts) == 1
    assert evts[0].actor_org_id == TEST_ORG_ID
    assert evts[0].client_id == TEST_AZP


def test_update_prompt_writes_event(client, db, auth_headers, sample_prompt):
    r = client.patch(f"/api/v1/prompts/{sample_prompt.id}", json={"title": "New Title"}, headers=auth_headers)
    assert r.status_code == 200
    evts = _events(db, entity_type="prompt", entity_id=str(sample_prompt.id), action="updated")
    assert len(evts) == 1


def test_update_prompt_status_writes_status_changed_event(client, db, auth_headers, dev_user):
    from src.models.prompt import Prompt
    p = Prompt(title="T", description="d", prompt_text="p", status="draft", visibility="private", featured=False, creator_id=dev_user.id)
    db.add(p)
    db.commit()
    db.refresh(p)

    r = client.patch(f"/api/v1/prompts/{p.id}", json={"status": "published_org"}, headers=auth_headers)
    assert r.status_code == 200
    evts = _events(db, entity_type="prompt", entity_id=str(p.id), action="status_changed")
    assert len(evts) == 1


def test_delete_prompt_writes_event(client, db, auth_headers, dev_user):
    from src.models.prompt import Prompt
    p = Prompt(title="To Delete", description="d", prompt_text="p", status="draft", visibility="private", featured=False, creator_id=dev_user.id)
    db.add(p)
    db.commit()
    db.refresh(p)
    pid = p.id

    r = client.delete(f"/api/v1/prompts/{pid}", headers=auth_headers)
    assert r.status_code == 204
    evts = _events(db, entity_type="prompt", entity_id=str(pid), action="deleted")
    assert len(evts) == 1


def test_submit_rating_writes_event(client, db, auth_headers, sample_prompt):
    r = client.post(f"/api/v1/prompts/{sample_prompt.id}/rate", json={"rating": 4}, headers=auth_headers)
    assert r.status_code == 200
    evts = _events(db, entity_type="rating", entity_id=str(sample_prompt.id), action="submitted")
    assert len(evts) == 1
    assert evts[0].client_id == TEST_AZP


# ── Categories ────────────────────────────────────────────────────────────────

def test_create_category_writes_event(client, db, auth_headers):
    r = client.post("/api/v1/categories", json={"name": "Audit Cat"}, headers=auth_headers)
    assert r.status_code == 201
    cat_id = r.json()["data"]["id"]
    evts = _events(db, entity_type="category", entity_id=str(cat_id), action="created")
    assert len(evts) == 1


def test_update_category_writes_event(client, db, auth_headers, sample_category):
    r = client.patch(f"/api/v1/categories/{sample_category.id}", json={"name": "Renamed"}, headers=auth_headers)
    assert r.status_code == 200
    evts = _events(db, entity_type="category", entity_id=str(sample_category.id), action="updated")
    assert len(evts) == 1


def test_delete_category_writes_event(client, db, auth_headers):
    from src.models.category import PromptCategory
    cat = PromptCategory(name="Del Cat")
    db.add(cat)
    db.commit()
    db.refresh(cat)
    cid = cat.id

    r = client.delete(f"/api/v1/categories/{cid}", headers=auth_headers)
    assert r.status_code == 204
    evts = _events(db, entity_type="category", entity_id=str(cid), action="deleted")
    assert len(evts) == 1


# ── Tags ─────────────────────────────────────────────────────────────────────

def test_create_tag_writes_event(client, db, auth_headers):
    r = client.post("/api/v1/tags", json={"name": "audit-tag"}, headers=auth_headers)
    assert r.status_code == 201
    tag_id = r.json()["data"]["id"]
    evts = _events(db, entity_type="tag", entity_id=str(tag_id), action="created")
    assert len(evts) == 1


def test_delete_tag_writes_event(client, db, auth_headers):
    from src.models.tag import PromptTag
    tag = PromptTag(name="del-tag")
    db.add(tag)
    db.commit()
    db.refresh(tag)
    tid = tag.id

    r = client.delete(f"/api/v1/tags/{tid}", headers=auth_headers)
    assert r.status_code == 204
    evts = _events(db, entity_type="tag", entity_id=str(tid), action="deleted")
    assert len(evts) == 1


# ── Uploads ───────────────────────────────────────────────────────────────────

def test_upload_image_writes_event(client, db, auth_headers):
    r = client.post(
        "/api/v1/uploads/images",
        files={"file": ("test.png", b"\x89PNG", "image/png")},
        headers=auth_headers,
    )
    assert r.status_code == 201
    evts = _events(db, entity_type="upload", action="created")
    assert len(evts) == 1


def test_delete_image_writes_event(client, db, auth_headers):
    # Upload first to get a valid key
    r = client.post(
        "/api/v1/uploads/images",
        files={"file": ("img.png", b"\x89PNG", "image/png")},
        headers=auth_headers,
    )
    assert r.status_code == 201
    key = r.json()["data"]["key"]

    r2 = client.delete(f"/api/v1/uploads/images/{key}", headers=auth_headers)
    assert r2.status_code == 204
    evts = _events(db, entity_type="upload", entity_id=key, action="deleted")
    assert len(evts) == 1


# ── Read endpoints do NOT write audit rows ────────────────────────────────────

def test_read_endpoints_do_not_write_events(client, db, auth_headers, sample_prompt):
    before = db.query(PromptEvent).count()
    client.get("/api/v1/prompts", headers=auth_headers)
    client.get(f"/api/v1/prompts/{sample_prompt.id}", headers=auth_headers)
    client.get("/api/v1/categories")
    client.get("/api/v1/tags")
    after = db.query(PromptEvent).count()
    assert after == before
