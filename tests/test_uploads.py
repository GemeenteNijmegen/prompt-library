import io
import pytest
from pathlib import Path

from starlette.testclient import TestClient

from tests.conftest import make_jwt


def make_client_with_storage(tmp_path: Path, db):
    from src.main import create_app
    from src.dependencies import get_db
    from src.storage.local import LocalFileSystemBackend
    from src.storage import get_storage_backend as _orig

    app = create_app()

    backend = LocalFileSystemBackend(base_path=tmp_path)

    def override_db():
        yield db

    def override_storage():
        return backend

    app.dependency_overrides[get_db] = override_db

    from src import storage as storage_mod
    app.dependency_overrides[storage_mod.get_storage_backend] = override_storage

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c, backend


@pytest.fixture()
def upload_client(tmp_path, db):
    yield from make_client_with_storage(tmp_path, db)


def image_payload(size: int = 100, filename: str = "test.png"):
    return {"file": (filename, io.BytesIO(b"x" * size), "image/png")}


def auth_headers():
    return {"Authorization": f"Bearer {make_jwt()}"}


def test_upload_image_success(upload_client):
    client, backend = upload_client
    resp = client.post(
        "/api/v1/uploads/images",
        files=image_payload(),
        headers=auth_headers(),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "data" in body
    assert "url" in body["data"]
    assert "key" in body["data"]


def test_upload_image_oversized_returns_413(upload_client):
    client, backend = upload_client
    resp = client.post(
        "/api/v1/uploads/images",
        files=image_payload(size=6 * 1024 * 1024),  # 6 MB
        headers=auth_headers(),
    )
    assert resp.status_code == 413


def test_upload_image_missing_auth_returns_401(upload_client):
    client, _ = upload_client
    resp = client.post(
        "/api/v1/uploads/images",
        files=image_payload(),
    )
    assert resp.status_code == 401


def test_upload_image_wrong_permission_returns_403(upload_client):
    client, _ = upload_client
    token = make_jwt(scope=["prompt:read"])
    resp = client.post(
        "/api/v1/uploads/images",
        files=image_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_delete_image_success(upload_client):
    client, backend = upload_client
    # First upload
    resp = client.post(
        "/api/v1/uploads/images",
        files=image_payload(),
        headers=auth_headers(),
    )
    key = resp.json()["data"]["key"]
    # Now delete
    del_resp = client.delete(
        f"/api/v1/uploads/images/{key}",
        headers=auth_headers(),
    )
    assert del_resp.status_code == 204


def test_delete_nonexistent_key_returns_404(upload_client):
    client, _ = upload_client
    resp = client.delete(
        "/api/v1/uploads/images/nonexistent.png",
        headers=auth_headers(),
    )
    assert resp.status_code == 404
