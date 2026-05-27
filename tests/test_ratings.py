import pytest


def test_submit_rating(client, auth_headers, sample_prompt):
    r = client.post(f"/api/v1/prompts/{sample_prompt.id}/rate", json={"rating": 4}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["data"]["rating"] == 4


def test_update_rating(client, auth_headers, sample_prompt):
    client.post(f"/api/v1/prompts/{sample_prompt.id}/rate", json={"rating": 3}, headers=auth_headers)
    r = client.post(f"/api/v1/prompts/{sample_prompt.id}/rate", json={"rating": 5}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["data"]["rating"] == 5


def test_get_user_rating(client, auth_headers, sample_prompt):
    client.post(f"/api/v1/prompts/{sample_prompt.id}/rate", json={"rating": 2}, headers=auth_headers)
    r = client.get(f"/api/v1/prompts/{sample_prompt.id}/rate", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["data"]["rating"] == 2


def test_get_user_rating_not_found(client, auth_headers, db, dev_user):
    from src.models.prompt import Prompt
    p = Prompt(
        title="No Rating",
        description="desc",
        prompt_text="text",
        status="published_org",
        visibility="public",
        creator_id=dev_user.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)

    r = client.get(f"/api/v1/prompts/{p.id}/rate", headers=auth_headers)
    assert r.status_code == 404


def test_get_rating_stats(client, auth_headers, sample_prompt):
    client.post(f"/api/v1/prompts/{sample_prompt.id}/rate", json={"rating": 4}, headers=auth_headers)
    r = client.get(f"/api/v1/prompts/{sample_prompt.id}/ratings")
    assert r.status_code == 200
    stats = r.json()["data"]
    assert "average" in stats
    assert "count" in stats
    assert "distribution" in stats
    assert stats["count"] >= 1


def test_rating_distribution(client, auth_headers, db, dev_user):
    from src.models.prompt import Prompt
    p = Prompt(
        title="Distribution Test",
        description="desc",
        prompt_text="text",
        status="published_org",
        visibility="public",
        creator_id=dev_user.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)

    client.post(f"/api/v1/prompts/{p.id}/rate", json={"rating": 5}, headers=auth_headers)

    r = client.get(f"/api/v1/prompts/{p.id}/ratings")
    stats = r.json()["data"]
    assert stats["distribution"]["5"] >= 1
    assert stats["average"] == 5.0


def test_rating_validation(client, auth_headers, sample_prompt):
    r = client.post(f"/api/v1/prompts/{sample_prompt.id}/rate", json={"rating": 6}, headers=auth_headers)
    assert r.status_code == 422


def test_rating_requires_auth(client, sample_prompt):
    r = client.post(f"/api/v1/prompts/{sample_prompt.id}/rate", json={"rating": 3})
    assert r.status_code == 401
