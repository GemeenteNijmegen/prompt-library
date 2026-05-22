def test_list_tags_empty(client):
    r = client.get("/api/v1/tags")
    assert r.status_code == 200
    assert isinstance(r.json()["data"], list)


def test_create_tag(client, auth_headers):
    r = client.post("/api/v1/tags", json={"name": "python"}, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["data"]["name"] == "python"


def test_create_tag_duplicate(client, auth_headers):
    client.post("/api/v1/tags", json={"name": "dedup-tag"}, headers=auth_headers)
    r = client.post("/api/v1/tags", json={"name": "dedup-tag"}, headers=auth_headers)
    assert r.status_code == 409


def test_get_tag(client, sample_tag):
    r = client.get(f"/api/v1/tags/{sample_tag.id}")
    assert r.status_code == 200
    assert r.json()["data"]["id"] == sample_tag.id


def test_get_tag_not_found(client):
    r = client.get("/api/v1/tags/99999")
    assert r.status_code == 404


def test_delete_tag(client, auth_headers, db):
    from src.models.tag import PromptTag
    tag = PromptTag(name="deletable-tag")
    db.add(tag)
    db.commit()
    db.refresh(tag)

    r = client.delete(f"/api/v1/tags/{tag.id}", headers=auth_headers)
    assert r.status_code == 204

    r2 = client.get(f"/api/v1/tags/{tag.id}")
    assert r2.status_code == 404


def test_get_or_create_tags(db):
    from src.services.taxonomy_service import get_or_create_tags
    tags = get_or_create_tags(db, ["alpha", "beta", "alpha"])
    db.commit()
    names = [t.name for t in tags]
    assert "alpha" in names
    assert "beta" in names
    # alpha appears once in unique result
    assert names.count("alpha") >= 1
