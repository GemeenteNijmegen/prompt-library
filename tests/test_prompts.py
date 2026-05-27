import pytest


def test_list_prompts_anonymous(client):
    r = client.get("/api/v1/prompts")
    assert r.status_code == 200
    body = r.json()
    assert "data" in body
    assert "meta" in body


def test_create_prompt(client, auth_headers):
    r = client.post("/api/v1/prompts", json={
        "title": "Test Prompt",
        "description": "A test description",
        "prompt_text": "Write about {topic}",
        "status": "draft",
        "visibility": "public",
    }, headers=auth_headers)
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["title"] == "Test Prompt"
    assert data["status"] == "draft"


def test_create_prompt_requires_auth(client):
    r = client.post("/api/v1/prompts", json={
        "title": "Test",
        "description": "desc",
        "prompt_text": "text",
    })
    assert r.status_code == 401


def test_get_prompt(client, auth_headers, sample_prompt):
    r = client.get(f"/api/v1/prompts/{sample_prompt.id}")
    assert r.status_code == 200
    assert r.json()["data"]["id"] == sample_prompt.id


def test_get_prompt_increments_view_count(client, sample_prompt):
    r1 = client.get(f"/api/v1/prompts/{sample_prompt.id}")
    r2 = client.get(f"/api/v1/prompts/{sample_prompt.id}")
    assert r2.json()["data"]["view_count"] == r1.json()["data"]["view_count"] + 1


def test_get_prompt_not_found(client):
    r = client.get("/api/v1/prompts/99999")
    assert r.status_code == 404


def test_update_prompt(client, auth_headers, sample_prompt):
    r = client.patch(
        f"/api/v1/prompts/{sample_prompt.id}",
        json={"title": "Updated Title"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["data"]["title"] == "Updated Title"


def test_use_prompt(client, sample_prompt):
    r = client.post(f"/api/v1/prompts/{sample_prompt.id}/use")
    assert r.status_code == 204


def test_list_featured(client, db, dev_user):
    from src.models.prompt import Prompt
    p = Prompt(
        title="Featured Prompt",
        description="desc",
        prompt_text="text",
        status="published_org",
        visibility="public",
        featured=True,
        creator_id=dev_user.id,
    )
    db.add(p)
    db.commit()

    r = client.get("/api/v1/prompts/featured")
    assert r.status_code == 200
    titles = [item["title"] for item in r.json()["data"]]
    assert "Featured Prompt" in titles


def test_status_transition_valid(client, auth_headers, db, dev_user):
    from src.models.prompt import Prompt
    p = Prompt(
        title="Transition",
        description="desc",
        prompt_text="text",
        status="draft",
        visibility="public",
        featured=False,
        creator_id=dev_user.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)

    r = client.patch(f"/api/v1/prompts/{p.id}", json={"status": "published_org"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "published_org"
    assert r.json()["data"]["published_at"] is not None


def test_status_transition_invalid(client, auth_headers, db, dev_user):
    from src.models.prompt import Prompt
    p = Prompt(
        title="Invalid Trans",
        description="desc",
        prompt_text="text",
        status="draft",
        visibility="public",
        featured=False,
        creator_id=dev_user.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)

    r = client.patch(f"/api/v1/prompts/{p.id}", json={"status": "archived"}, headers=auth_headers)
    assert r.status_code == 409


def test_search_prompts(client, auth_headers, db, dev_user):
    from src.models.prompt import Prompt
    p = Prompt(
        title="Unique Searchable XYZ",
        description="desc",
        prompt_text="text",
        status="published_org",
        visibility="public",
        featured=False,
        creator_id=dev_user.id,
    )
    db.add(p)
    db.commit()

    r = client.get("/api/v1/prompts?search=Unique+Searchable+XYZ", headers=auth_headers)
    assert r.status_code == 200
    titles = [item["title"] for item in r.json()["data"]]
    assert "Unique Searchable XYZ" in titles


def test_prompt_with_tags(client, auth_headers):
    r = client.post("/api/v1/prompts", json={
        "title": "Tagged Prompt",
        "description": "desc",
        "prompt_text": "text",
        "tag_names": ["ai", "writing"],
    }, headers=auth_headers)
    assert r.status_code == 201
    tags = [t["name"] for t in r.json()["data"]["tags"]]
    assert "ai" in tags
    assert "writing" in tags
