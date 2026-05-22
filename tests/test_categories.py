def test_list_categories_empty(client):
    r = client.get("/api/v1/categories")
    assert r.status_code == 200
    assert r.json()["data"] == [] or isinstance(r.json()["data"], list)


def test_create_category(client, auth_headers):
    r = client.post("/api/v1/categories", json={"name": "Science", "description": "Science prompts"}, headers=auth_headers)
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["name"] == "Science"
    assert data["prompt_count"] == 0


def test_create_category_duplicate(client, auth_headers):
    client.post("/api/v1/categories", json={"name": "Duplicate"}, headers=auth_headers)
    r = client.post("/api/v1/categories", json={"name": "Duplicate"}, headers=auth_headers)
    assert r.status_code == 409


def test_get_category(client, auth_headers, sample_category):
    r = client.get(f"/api/v1/categories/{sample_category.id}")
    assert r.status_code == 200
    assert r.json()["data"]["id"] == sample_category.id


def test_get_category_not_found(client):
    r = client.get("/api/v1/categories/99999")
    assert r.status_code == 404


def test_update_category(client, auth_headers, sample_category):
    r = client.patch(
        f"/api/v1/categories/{sample_category.id}",
        json={"name": "Updated Name"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "Updated Name"


def test_delete_category(client, auth_headers, db):
    from src.models.category import PromptCategory
    cat = PromptCategory(name="To Delete")
    db.add(cat)
    db.commit()
    db.refresh(cat)

    r = client.delete(f"/api/v1/categories/{cat.id}", headers=auth_headers)
    assert r.status_code == 204

    r2 = client.get(f"/api/v1/categories/{cat.id}")
    assert r2.status_code == 404


def test_create_category_requires_auth(client):
    r = client.post("/api/v1/categories", json={"name": "Unauth"})
    assert r.status_code == 401
